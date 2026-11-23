# -*- coding: utf-8 -*-
"""验证新提交的两个任务快照"""
import sys, json
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.200', port=3307, user='ai_media_app',
          password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
          charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=20)
c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
IDS = ('job-d7b59329b2dd', 'job-6048f5241747')
for jid in IDS:
    cur.execute("select id,status,progress,payload_json from ai_project_jobs where id=%s", (jid,))
    r = cur.fetchone()
    if not r:
        print(jid, '不存在'); continue
    p = json.loads(r['payload_json']) if r['payload_json'] else {}
    print('==', jid, r['status'], str(r['progress']) + '%')
    print('   strategy', p.get('strategy'), '| shot_count', p.get('shot_count'))
    for k in ('shots', 'source_shots', 'render_plan'):
        v = p.get(k)
        if isinstance(v, list):
            print('   %s: %d 项' % (k, len(v)))
            if v and k == 'shots':
                first = v[0] if isinstance(v[0], dict) else {}
                print('      首镜:', str(first.get('heading') or first.get('title') or '')[:90])
                print('      机位:', str(first.get('camera') or '')[:70])
        elif v:
            print('   %s:' % k, str(v)[:100])
print()
cur.execute("select id,status,progress from ai_project_jobs where project_id='proj-dd6ca6baac23473b' "
            "and status in ('queued','running','preparing','prompt_generation','comfy_queued') order by created_at")
print('当前活跃/排队任务:', cur.fetchall())
c.close()
