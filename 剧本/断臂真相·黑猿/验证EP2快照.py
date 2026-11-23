# -*- coding: utf-8 -*-
"""验证 EP2 新任务快照包含新增镜头"""
import sys, json
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select payload_json from ai_project_jobs where id='job-28c2e19edf47'")
p = json.loads(cur.fetchone()['payload_json'])
print('shot_count =', p.get('shot_count'), '| total_duration =', p.get('total_duration_seconds'))
src = p.get('source_shots') or p.get('shots') or []
print('快照镜头数 =', len(src))
titles = []
for s in src:
    h = s.get('heading') or s.get('title') or ''
    titles.append(h.split('（')[0].strip() or '?')
print('\n快照标题序列:')
print(' / '.join(titles))
need = ['静', '咬牙', '看袖管', '探进袖管', '嘴唇在抖', '埋进袖管', '草帽停在半空']
missing = [n for n in need if n not in titles]
print('\n新镜头是否都在:', '全部命中' if not missing else f'缺 {missing}')
c.close()
