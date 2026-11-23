# -*- coding: utf-8 -*-
"""监控 EP2(补10镜) + EP3(19镜)，连新库 192.168.10.200:3307，出片即下载、满镜自动拼接"""
import sys, time, json, os, subprocess, urllib.request
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql, requests

DB = dict(host='192.168.10.200', port=3307, user='ai_media_app',
          password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
          charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=20)
PID = 'proj-dd6ca6baac23473b'
JOBS = ['job-d7b59329b2dd', 'job-6048f5241747']
ACTIVE = {'queued', 'running', 'preparing', 'prompt_generation', 'comfy_queued',
          'uploading', 'assembling', 'downloading'}
BASE_OUT = 'D:/zlyun/Toonflow/本地视频工作台/剧本/断臂真相·黑猿/对照'
TOTAL = {2: 30, 3: 19}

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
    for i, b in enumerate(beats, 1):
        u = b.get('video_url') or b.get('render_url')
        if not u:
            continue
        fn = os.path.join(out, 'EP%d_%02d.mp4' % (epnum, i))
        if os.path.exists(fn) and os.path.getsize(fn) > 10000:
            continue
        try:
            urllib.request.urlretrieve(u, fn)
        except Exception as e:
            print('  下载失败 EP%d-%d %s' % (epnum, i, e), flush=True)


def concat(epnum):
    n = TOTAL[epnum]
    out = os.path.join(BASE_OUT, '新片EP%d' % epnum)
    files = [os.path.join(out, 'EP%d_%02d.mp4' % (epnum, k)) for k in range(1, n + 1)]
    miss = [k for k, f in enumerate(files, 1) if not os.path.exists(f)]
    if miss:
        return False
    lst = os.path.join(out, 'list_all.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.write('\n'.join("file '%s'" % x.replace('\\', '/') for x in files))
    dst = os.path.join(out, '新片EP%d_完整%d镜.mp4' % (epnum, n))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                    '-i', lst, '-c', 'copy', dst], check=False)
    print('  EP%d 拼接完成 -> %s' % (epnum, dst), flush=True)
    return True


last_sig = None
stall = 0
done_eps = set()
for it in range(400):
    cur.execute("select id,status,progress,error_message,lease_updated_at from ai_project_jobs "
                "where id in (%s,%s)", JOBS)
    rows = {r['id']: r for r in cur.fetchall()}
    b2, h2 = snap(2)
    b3, h3 = snap(3)

    sig = (tuple(sorted((r['id'], r['status'], r['progress']) for r in rows.values())),
           len(h2), len(h3))
    if sig != last_sig:
        try:
            q = requests.get('http://192.168.10.54:8188/queue', timeout=5).json()
            remote = 'run%d/pend%d' % (len(q.get('queue_running', [])), len(q.get('queue_pending', [])))
        except Exception:
            remote = '不可达'
        act = [(r['id'][-4:], r['status'], r['progress']) for r in rows.values()
               if r['status'] in ACTIVE]
        print('[%03d] EP2 %d/30  EP3 %d/19 | %s | 远端 %s'
              % (it, len(h2), len(h3), act if act else '无活跃', remote), flush=True)
        last_sig = sig
        stall = 0
        download(2, b2)
        download(3, b3)
    else:
        stall += 1
        if stall % 15 == 0:
            print('[%03d] 状态未变 %d 分钟  EP2 %d/30 EP3 %d/19'
                  % (it, stall * 3, len(h2), len(h3)), flush=True)
        if stall % 20 == 0:
            print('!!! 停滞告警，建议检查远端队列与本地心跳', flush=True)

    for epnum, h in ((2, h2), (3, h3)):
        if len(h) == TOTAL[epnum] and epnum not in done_eps:
            if concat(epnum):
                done_eps.add(epnum)

    if all(r['status'] not in ACTIVE for r in rows.values()):
        print('全部任务结束', flush=True)
        for jid, r in rows.items():
            print('  ', jid, r['status'], r['progress'], str(r['error_message'])[:140], flush=True)
        download(2, b2)
        download(3, b3)
        concat(2)
        concat(3)
        print('MONITOR_DONE', flush=True)
        break
    time.sleep(180)
c.close()
