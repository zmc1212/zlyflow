# -*- coding: utf-8 -*-
"""诊断 EP2 写稿卡死 + EP1 三个排队任务"""
import sys, json, datetime
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'
ACTIVE = {'queued', 'running', 'preparing', 'prompt_generation', 'comfy_queued',
          'uploading', 'assembling', 'downloading'}

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
now = datetime.datetime.now()
print('现在', now.strftime('%Y-%m-%d %H:%M:%S'))
print()

cur.execute("""select id,title,status,progress,worker_id,lease_updated_at,updated_at,
                      created_at,error_message,result_url,payload_json
               from ai_project_jobs where project_id=%s order by created_at desc limit 10""", (PID,))
rows = cur.fetchall()
eps = {}
cur.execute("select id,episode_num from ai_project_episodes where project_id=%s", (PID,))
for r in cur.fetchall():
    eps[r['id']] = r['episode_num']

for r in rows:
    ep = eps.get(r.get('episode_id'), '?')
    lease = r['lease_updated_at']
    age = ''
    if isinstance(lease, datetime.datetime):
        age = '%d 分钟前' % int((now - lease).total_seconds() / 60)
    p = {}
    try:
        p = json.loads(r['payload_json']) if r['payload_json'] else {}
    except Exception:
        pass
    print('== %s EP%s %s %s%%' % (r['id'], ep, r['status'], r['progress']))
    print('   创建', r['created_at'], '| 更新', r['updated_at'], '| lease', lease, age)
    print('   worker', r['worker_id'], '| strategy', p.get('strategy'), '| shot_count', p.get('shot_count'))
    print('   error', str(r['error_message'])[:200])
    if p.get('stage') or p.get('current_index') is not None:
        for k in ('stage', 'current_index', 'current_shot', 'segment_index'):
            if k in p:
                print('   ', k, '=', p[k])
    print()
c.close()
