# -*- coding: utf-8 -*-
"""提交 EP2 补拍(剩10镜) + EP3 首生成(19镜)
会话写入新库 192.168.10.200:3307（后端运行库）
"""
import sys, json, hashlib, secrets, datetime
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql, requests

DB = dict(host='192.168.10.200', port=3307, user='ai_media_app',
          password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
          charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=20)
PID = 'proj-dd6ca6baac23473b'
BASE = 'http://127.0.0.1:7865'

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
token = secrets.token_urlsafe(32)
th = hashlib.sha256(token.encode()).hexdigest()
csrf = hashlib.sha256(('zly-ai-video-studio-csrf:' + token).encode()).hexdigest()
now = datetime.datetime.now(datetime.timezone.utc)
cur.execute("insert into sessions (token_hash,user_id,expires_at,created_at) values (%s,%s,%s,%s)",
            (th, '8UKOFV4-iyb37iqN', (now + datetime.timedelta(hours=5)).isoformat(), now.isoformat()))
s = requests.Session()
s.cookies.set('zly_ai_video_studio_session', token)
H = {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}

try:
    # 先让第 2 集补完最后 10 镜（断臂集尽快完整）
    cur.execute("select id,shots_count,data_json from ai_project_episodes "
                "where project_id=%s and episode_num=2", (PID,))
    ep2 = cur.fetchone()
    miss2 = [i for i, b in enumerate(json.loads(ep2['data_json'])['beats'], 1)
             if not (b.get('video_url') or b.get('render_url'))]
    print('EP2 共 %d 镜，缺 %d: %s' % (ep2['shots_count'], len(miss2), miss2))
    r = s.post(f"{BASE}/api/projects/{PID}/episodes/{ep2['id']}/generate-video",
               headers=H, data=json.dumps({"strategy": "gap_fill"}).encode(), timeout=180)
    print('  EP2 提交', r.status_code, r.text[:420])

    # 第 3 集全 19 镜，默认整集提交
    cur.execute("select id,shots_count from ai_project_episodes "
                "where project_id=%s and episode_num=3", (PID,))
    ep3 = cur.fetchone()
    print('\nEP3 共 %d 镜（全新）' % ep3['shots_count'])
    r = s.post(f"{BASE}/api/projects/{PID}/episodes/{ep3['id']}/generate-video",
               headers=H, data=json.dumps({}).encode(), timeout=180)
    print('  EP3 提交', r.status_code, r.text[:420])
finally:
    cur.execute("delete from sessions where token_hash=%s", (th,))
    c.close()
