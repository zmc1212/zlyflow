# -*- coding: utf-8 -*-
"""查看第 3 集 13 镜完整内容"""
import sys, json
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4', autocommit=True)
c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,data_json from ai_project_episodes "
            "where project_id='proj-dd6ca6baac23473b' and episode_num=3")
r = cur.fetchone()
d = json.loads(r['data_json'])
beats = d['beats']
print('EP3 id', r['id'], '| beats', len(beats), '| keys', list(d.keys()))
print('beat0 字段:', list(beats[0].keys()))
print()
for i, b in enumerate(beats, 1):
    print('=== 镜%02d %s' % (i, b.get('heading', '')))
    print('   时长', b.get('video_duration'), '| kind', b.get('kind'))
    print('   动作:', (b.get('action') or '')[:140])
    print('   台词:', (b.get('dialogue') or '—')[:100])
    print('   机位:', (b.get('camera') or '')[:90])
    print('   角色:', b.get('characters'), '| 场景:', b.get('scene'), '| 道具:', b.get('props'))
    p = b.get('h3_prompt') or ''
    print('   h3_prompt 长度', len(p))
    if p:
        import re
        seg = re.findall(r'camera:\s*([^\n。]{0,80})', p)
        print('   提示词机位:', (seg[0] if seg else '（无 camera: 段）')[:90])
    print()
c.close()
