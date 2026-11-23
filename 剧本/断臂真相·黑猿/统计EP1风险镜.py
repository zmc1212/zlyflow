# -*- coding: utf-8 -*-
"""统计第1集各镜运镜跨度与落幅可读性风险"""
import sys, json, re
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
ORDER = ['大全景', '全景', '中景', '中近景', '近景', '特写', '大特写']

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select data_json from ai_project_episodes "
            "where project_id='proj-dd6ca6baac23473b' and episode_num=1")
beats = json.loads(cur.fetchone()['data_json'])['beats']

risky = []
for b in beats:
    cam = b.get('camera') or ''
    got = b.get('video_url') or b.get('render_url')
    found = [s for s in ORDER if s in cam]
    # 起幅景别取第一个出现，落幅取紧跟箭头后的
    span = None
    if '→' in cam:
        left, right = cam.split('→', 1)
        l = next((s for s in ORDER if s in left), None)
        r = next((s for s in ORDER if s in right), None)
        if l and r:
            span = abs(ORDER.index(r) - ORDER.index(l))
    flag = ''
    if span is not None and span >= 2:
        flag = '★跨%d档' % span
    elif span == 1 and ORDER.index(next(s for s in ORDER if s in cam.split('→')[1])) >= 5:
        flag = '△推到特写'
    if flag:
        risky.append((b['sequence'], cam, flag, bool(got)))

print('%-4s %-52s %-8s %s' % ('镜', '机位', '风险', '已出片'))
for s, cam, f, done in risky:
    print('%-4d %-52s %-8s %s' % (s, cam[:50], f, '是' if done else '否'))
print(f'\n共 {len(risky)} 镜存在推到底风险 / 全部 {len(beats)} 镜')
