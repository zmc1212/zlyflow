# -*- coding: utf-8 -*-
"""双任务 + 远端健康监控，卡死时自动报警"""
import sys, time, json, datetime
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql, requests

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'
REMOTE = 'http://192.168.10.54:8188'
ACTIVE = {'queued', 'running', 'preparing', 'prompt_generation', 'comfy_queued',
          'uploading', 'assembling', 'downloading'}

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
last = {}
stuck_since = {}
for i in range(240):
    cur.execute("""select id,title,status,progress from ai_project_jobs
                   where project_id=%s and status in ('queued','running','preparing',
                   'prompt_generation','comfy_queued','uploading','assembling','downloading')
                   order by created_at""", (PID,))
    rows = cur.fetchall()
    parts = []
    for r in rows:
        key = r['id']
        sig = (r['status'], r['progress'])
        if last.get(key) == sig:
            stuck_since.setdefault(key, time.time())
            stuck_min = int((time.time() - stuck_since[key]) / 60)
            mark = f' 停滞{stuck_min}m' if stuck_min >= 25 else ''
        else:
            stuck_since.pop(key, None)
            stuck_min = 0
            mark = ''
        last[key] = sig
        parts.append(f"{r['title'][-8:]} {r['status']} {r['progress']}%{mark}")

    # 远端健康
    health = ''
    try:
        st = requests.get(f'{REMOTE}/system_stats', timeout=6).json()
        free = round(st['system']['ram_free'] / 1e9, 1)
        q = requests.get(f'{REMOTE}/queue', timeout=6).json()
        run = len(q.get('queue_running', []))
        health = f" | 远端 内存{free}G 跑{run}"
    except Exception as e:
        health = f' | 远端不可达'

    print(f'[{i}] ' + ' || '.join(parts) + health, flush=True)

    # 报警：任一任务停滞超过 40 分钟
    if any(int((time.time() - t) / 60) >= 40 for t in stuck_since.values()) and i % 3 == 0:
        print('!!! 检测到任务停滞，建议检查远端队列', flush=True)

    if not rows:
        print('ALL_IDLE 队列已空', flush=True)
        break
    time.sleep(180)
c.close()
