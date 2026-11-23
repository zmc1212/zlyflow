# -*- coding: utf-8 -*-
"""中断后状态检查"""
import sys, json, datetime
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,status,progress,error_message,updated_at from ai_project_jobs "
            "where id in ('job-7490f3e578a9','job-28c2e19edf47')")
for r in cur.fetchall():
    print(r['id'], r['status'], r['progress'], '%', '| err:', str(r['error_message'])[:120], '| upd', r['updated_at'])
cur.execute("select data_json from ai_project_episodes "
            "where project_id='proj-dd6ca6baac23473b' and episode_num=1")
beats = json.loads(cur.fetchone()['data_json'])['beats']
done = [b['sequence'] for b in beats if b.get('video_url') or b.get('render_url')]
print('\nEP1 已出镜:', done, f'({len(done)}/24)')
c.close()
