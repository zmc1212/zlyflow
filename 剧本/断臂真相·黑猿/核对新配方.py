# -*- coding: utf-8 -*-
"""核对已有片镜头是否为固定机位新配方"""
import sys, json, re
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
for epnum in (1, 2):
    cur.execute("select data_json from ai_project_episodes where project_id=%s and episode_num=%s",
                (PID, epnum))
    beats = json.loads(cur.fetchone()['data_json'])['beats']
    print('======== EP%s 已有片镜头 ========' % epnum)
    for i, b in enumerate(beats, 1):
        u = b.get('video_url') or b.get('render_url')
        if not u:
            continue
        p = b.get('h3_prompt') or ''
        cam = b.get('camera') or ''
        lock = ('固定' in cam) or ('locked off' in p.lower())
        seg = re.findall(r'camera:\s*([^\n。]{0,70})', p)
        print('%2d %s | %s | %s' % (i, '固定' if lock else '运镜',
                                     round(float(b.get('video_duration') or 0), 1), b['heading'][:42]))
        print('     camera字段:', cam[:70])
        print('     提示词机位:', (seg[0] if seg else '（无 camera: 段）')[:80])
    print()
c.close()
