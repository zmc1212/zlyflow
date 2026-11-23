# -*- coding: utf-8 -*-
"""提交第 1 集补拍（gap_fill 只跑缺失镜）"""
import sys, json, hashlib, secrets, datetime
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql, requests

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
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
c.commit()
s = requests.Session()
s.cookies.set('zly_ai_video_studio_session', token)
H = {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
try:
    cur.execute("select id, shots_count from ai_project_episodes where project_id=%s and episode_num=1", (PID,))
    ep = cur.fetchone()
    print('EP1 镜头数', ep['shots_count'])
    resp = s.post(f"{BASE}/api/projects/{PID}/episodes/{ep['id']}/generate-video",
                  headers=H, data=json.dumps({"strategy": "gap_fill"}).encode(), timeout=180)
    print('提交结果', resp.status_code)
    print(resp.text[:600])
finally:
    cur.execute("delete from sessions where token_hash=%s", (th,))
    c.commit()
    c.close()
