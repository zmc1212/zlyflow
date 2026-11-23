# -*- coding: utf-8 -*-
"""监控 EP1(14镜) + EP2(25镜) 补拍，出片即下载，跑完自动拼接"""
import sys, time, json, os, subprocess, urllib.request
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'
JOBS = ['job-eaccc3f1e632', 'job-bc0b6abd6db3', 'job-37875c396047']
ACTIVE = {'queued', 'running', 'preparing', 'prompt_generation', 'comfy_queued',
          'uploading', 'assembling', 'downloading'}
BASE_OUT = 'D:/zlyun/Toonflow/本地视频工作台/剧本/断臂真相·黑猿/对照'

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)


def snap(epnum):
    cur.execute("select data_json from ai_project_episodes where project_id=%s and episode_num=%s",
                (PID, epnum))
    beats = json.loads(cur.fetchone()['data_json'])['beats']
    have = [i for i, b in enumerate(beats, 1) if b.get('video_url') or b.get('render_url')]
    return beats, have


def download(epnum, beats):
    out = os.path.join(BASE_OUT, '新片EP%d' % epnum)
    os.makedirs(out, exist_ok=True)
    got = 0
    for i, b in enumerate(beats, 1):
        u = b.get('video_url') or b.get('render_url')
        if not u:
            continue
        fn = os.path.join(out, 'EP%d_%02d.mp4' % (epnum, i))
        if os.path.exists(fn) and os.path.getsize(fn) > 10000:
            continue
        try:
            urllib.request.urlretrieve(u, fn)
            got += 1
        except Exception as e:
            print('  下载失败', epnum, i, e, flush=True)
    return got


def concat(epnum, n):
    out = os.path.join(BASE_OUT, '新片EP%d' % epnum)
    files = [os.path.join(out, 'EP%d_%02d.mp4' % (epnum, k)) for k in range(1, n + 1)]
    miss = [k for k, f in enumerate(files, 1) if not os.path.exists(f)]
    if miss:
        print('  EP%d 缺镜 %s，暂不拼接' % (epnum, miss), flush=True)
        return
    lst = os.path.join(out, 'list_all.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.write('\n'.join("file '%s'" % x.replace('\\', '/') for x in files))
    dst = os.path.join(out, '新片EP%d_完整%d镜.mp4' % (epnum, n))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                    '-i', lst, '-c', 'copy', dst], check=False)
    print('  EP%d 拼接完成 -> %s' % (epnum, dst), flush=True)


last1 = last2 = -1
stall = 0
prev_sig = None
for it in range(400):
    cur.execute("select id,status,progress,error_message,lease_updated_at from ai_project_jobs "
                "where id in (%s,%s,%s)", JOBS)
    rows = {r['id']: r for r in cur.fetchall()}
    b1, h1 = snap(1)
    b2, h2 = snap(2)

    act = [(r['id'][-4:], r['status'], r['progress']) for r in rows.values() if r['status'] in ACTIVE]
    sig = (tuple(sorted((r['id'], r['status'], r['progress']) for r in rows.values())), len(h1), len(h2))
    if sig != prev_sig:
        remote = '?'
        try:
            import requests
            q = requests.get('http://192.168.10.54:8188/queue', timeout=5).json()
            remote = 'run%d pend%d' % (len(q.get('queue_running', [])), len(q.get('queue_pending', [])))
        except Exception:
            remote = '不可达'
        print('[%02d] EP1 %d/26  EP2 %d/30 | 活跃 %s | 远端 %s'
              % (it, len(h1), len(h2), act if act else '无', remote), flush=True)
        prev_sig = sig
        stall = 0
        download(1, b1)
        download(2, b2)
    else:
        stall += 1
        if stall % 15 == 0:
            print('[%02d] 状态未变 %d 分钟，EP1 %d/26 EP2 %d/30 活跃 %s'
                  % (it, stall * 3, len(h1), len(h2), act if act else '无'), flush=True)

    if len(h1) == 26:
        concat(1, 26)
    if len(h2) == 30:
        concat(2, 30)

    all_done = all(r['status'] not in ACTIVE for r in rows.values())
    if all_done:
        print('全部任务结束', flush=True)
        for jid, r in rows.items():
            print('  ', jid, r['status'], r['progress'], str(r['error_message'])[:120], flush=True)
        download(1, b1)
        download(2, b2)
        concat(1, 26)
        concat(2, 30)
        print('MONITOR_DONE', flush=True)
        break
    time.sleep(180)
c.close()
