# -*- coding: utf-8 -*-
"""下载第 1 集 26 镜并拼接成完整片（新库）"""
import sys, json, os, subprocess, urllib.request
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.200', port=3307, user='ai_media_app',
          password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
          charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=20)
PID = 'proj-dd6ca6baac23473b'
OUT = 'D:/zlyun/Toonflow/本地视频工作台/剧本/断臂真相·黑猿/对照/新片EP1'
os.makedirs(OUT, exist_ok=True)

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select data_json from ai_project_episodes where project_id=%s and episode_num=1", (PID,))
beats = json.loads(cur.fetchone()['data_json'])['beats']
c.close()
print('EP1 共 %d 镜' % len(beats))

files = []
for i, b in enumerate(beats, 1):
    u = b.get('video_url') or b.get('render_url')
    fn = os.path.join(OUT, 'EP1_%02d.mp4' % i)
    if not u:
        print('  镜%d 无 URL' % i); continue
    if not (os.path.exists(fn) and os.path.getsize(fn) > 10000):
        try:
            urllib.request.urlretrieve(u, fn)
            print('  下载 %02d  %d KB' % (i, os.path.getsize(fn) // 1024))
        except Exception as e:
            print('  下载失败 %02d %s' % (i, e)); continue
    files.append(fn)

print('本地齐备 %d/%d' % (len(files), len(beats)))
if len(files) == len(beats):
    lst = os.path.join(OUT, 'list_26.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.write('\n'.join("file '%s'" % x.replace('\\', '/') for x in files))
    dst = os.path.join(OUT, '新片EP1_完整26镜.mp4')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                    '-i', lst, '-c', 'copy', dst], check=False)
    if os.path.exists(dst):
        d = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration,size', '-of', 'csv=p=0', dst],
                           capture_output=True, text=True).stdout.strip()
        print('成片:', dst, '|', d)
