# -*- coding: utf-8 -*-
"""核对新库(192.168.10.200:3307)与旧库(125:3306)的项目数据"""
import sys, json
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

PID = 'proj-dd6ca6baac23473b'
NEW = dict(host='192.168.10.200', port=3307, user='ai_media_app',
           password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
           charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=15)
OLD = dict(host='192.168.10.125', port=3306, user='root', password='123456',
           database='ai-media', charset='utf8mb4', autocommit=True,
           connect_timeout=8, read_timeout=15)

for label, cfg in (('新库 200:3307', NEW), ('旧库 125:3306', OLD)):
    print('============== %s ==============' % label)
    try:
        c = pymysql.connect(**cfg)
    except Exception as e:
        print('  连接失败:', str(e)[:150]); print(); continue
    cur = c.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("select id,title,status,shots_count,updated_at from ai_project_episodes "
                    "where project_id=%s order by episode_num", (PID,))
        for r in cur.fetchall():
            print('  EP? %s  shots=%s  title=%s  upd=%s' %
                  (r['id'], r['shots_count'], str(r['title'])[:24], r['updated_at']))
        cur.execute("select episode_num, shots_count, data_json from ai_project_episodes "
                    "where project_id=%s order by episode_num", (PID,))
        for r in cur.fetchall():
            d = json.loads(r['data_json']) if r['data_json'] else {}
            beats = d.get('beats') or []
            have = [i for i, b in enumerate(beats, 1) if b.get('video_url') or b.get('render_url')]
            print('  EP%s: %d 镜, 有片 %d %s' % (r['episode_num'], len(beats), len(have), have[:30]))
        cur.execute("select id,status,progress,created_at,updated_at from ai_project_jobs "
                    "where project_id=%s order by created_at desc limit 6", (PID,))
        print('  最近任务:')
        for r in cur.fetchall():
            print('   ', r['id'], r['status'], r['progress'], r['created_at'])
    except Exception as e:
        print('  查询出错:', str(e)[:160])
    c.close()
    print()
