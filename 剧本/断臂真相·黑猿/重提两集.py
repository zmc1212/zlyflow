# -*- coding: utf-8 -*-
"""按 gap_fill 重新提交第 1、2 集（只跑缺失镜，不覆盖已出片）"""
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
    for epnum in (1, 2):
        cur.execute("select id, shots_count, data_json from ai_project_episodes "
                    "where project_id=%s and episode_num=%s", (PID, epnum))
        ep = cur.fetchone()
        beats = json.loads(ep['data_json'])['beats']
        miss = [i for i, b in enumerate(beats, 1)
                if not (b.get('video_url') or b.get('render_url'))]
        print('EP%s 共 %d 镜，缺 %d 镜: %s' % (epnum, ep['shots_count'], len(miss), miss))
        resp = s.post(f"{BASE}/api/projects/{PID}/episodes/{ep['id']}/generate-video",
                      headers=H, data=json.dumps({"strategy": "gap_fill"}).encode(), timeout=180)
        print('  提交', resp.status_code, resp.text[:400])
        print()
finally:
    cur.execute("delete from sessions where token_hash=%s", (th,))
    c.commit()
    c.close()
