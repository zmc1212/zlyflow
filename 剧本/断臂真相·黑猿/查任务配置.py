# -*- coding: utf-8 -*-
"""查任务实际连接的 comfy 地址与 GPU 占用情况"""
import sys, json
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,payload_json from ai_project_jobs "
            "where id in ('job-7490f3e578a9','job-28c2e19edf47')")
for r in cur.fetchall():
    p = json.loads(r['payload_json'])
    print(r['id'])
    for k in ('comfy_base_url', 'api_endpoint', 'width', 'height', 'steps',
              'video_steps', 'audio_steps', 'audio_mode', 'workflow', 'model',
              'target_type', 'duration_per_beat', 'refine_enabled', 'seed'):
        if k in p:
            print('   ', k, '=', p[k])
    print()
c.close()
