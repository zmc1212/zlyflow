# -*- coding: utf-8 -*-
"""盘点两集镜头状态"""
import sys, json
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("""select episode_num, id, status, shots_count, data_json
               from ai_project_episodes where project_id=%s order by episode_num""", (PID,))
for r in cur.fetchall():
    d = json.loads(r['data_json']) if r['data_json'] else {}
    beats = d.get('beats') or []
    have = [i for i, b in enumerate(beats, 1) if b.get('video_url') or b.get('render_url')]
    miss = [i for i, b in enumerate(beats, 1) if not (b.get('video_url') or b.get('render_url'))]
    dur = sum(float(b.get('video_duration') or 0) for b in beats)
    print('==== EP%s  status=%s  shots_count=%s  beats=%d  总时长=%.0fs'
          % (r['episode_num'], r['status'], r['shots_count'], len(beats), dur))
    print('   有片 %d 镜: %s' % (len(have), have))
    print('   缺片 %d 镜: %s' % (len(miss), miss))
    print('   episode_video_url:', (d.get('episode_video_url') or '-')[:110])
    print()
c.close()
