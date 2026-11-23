# -*- coding: utf-8 -*-
"""修正 camera 里秒数与 video_duration 不一致的问题"""
import sys, json, re
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,data_json from ai_project_episodes "
            "where project_id='proj-dd6ca6baac23473b' and episode_num=2")
r = cur.fetchone()
d = json.loads(r['data_json'])

fixed = []
for b in d['beats']:
    dur = int(float(b.get('video_duration') or 5))
    cam = b.get('camera') or ''
    new = re.sub(r'(\d+)\s*秒', f'{dur} 秒', cam)
    if new != cam:
        fixed.append((b['sequence'], cam, new))
        b['camera'] = new
        parts = b['heading'].split(' · ')
        if len(parts) >= 3:
            b['heading'] = ' · '.join(parts[:2] + [new])

cur.execute("update ai_project_episodes set data_json=%s where id=%s",
            (json.dumps(d, ensure_ascii=False), r['id']))
c.commit()

print('修正秒数不一致', len(fixed), '处')
for s, o, n in fixed:
    print(f'  镜{s}: {o[-24:]}  ->  {n[-24:]}')

tot = len(d['beats'])
lock = sum(1 for b in d['beats'] if '固定' in (b.get('camera') or ''))
print(f'\n固定机位 {lock} / 运镜 {tot - lock}（共 {tot} 镜）')
c.close()
