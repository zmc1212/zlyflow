# -*- coding: utf-8 -*-
"""第 1 集 26 镜总览联系表（每镜取中间帧）"""
import subprocess, os, json, sys
from PIL import Image, ImageDraw, ImageFont

OUT = 'D:/zlyun/Toonflow/本地视频工作台/剧本/断臂真相·黑猿/对照/新片EP1'
FR = os.path.join(OUT, '帧')
os.makedirs(FR, exist_ok=True)
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql
DB = dict(host='192.168.10.200', port=3307, user='ai_media_app',
          password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
          charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=20)
c = pymysql.connect(**DB); cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select data_json from ai_project_episodes "
            "where project_id='proj-dd6ca6baac23473b' and episode_num=1")
beats = json.loads(cur.fetchone()['data_json'])['beats']
c.close()

font_path = 'C:/Windows/Fonts/msyh.ttc'
font = ImageFont.truetype(font_path, 17)
font_s = ImageFont.truetype(font_path, 13)

CW, CH, COLS = 360, 238, 4
ROWS = (len(beats) + COLS - 1) // COLS
canvas = Image.new('RGB', (CW * COLS, CH * ROWS), (24, 26, 30))
draw = ImageDraw.Draw(canvas)

for i, b in enumerate(beats, 1):
    src = os.path.join(OUT, 'EP1_%02d.mp4' % i)
    mid = os.path.join(FR, 'm%02d.png' % i)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                'format=duration', '-of', 'csv=p=0', src],
                               capture_output=True, text=True).stdout.strip() or 5)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', '%.2f' % (dur / 2),
                    '-i', src, '-frames:v', '1', mid], check=True)
    im = Image.open(mid).convert('RGB')
    im.thumbnail((CW - 8, 200))
    col, row = (i - 1) % COLS, (i - 1) // COLS
    x, y = col * CW, row * CH
    canvas.paste(im, (x + (CW - im.width) // 2, y + 4))
    title = b['heading'].split('（')[0][:16]
    draw.rectangle([x, y + 204, x + CW, y + CH], fill=(32, 34, 40))
    draw.text((x + 8, y + 207), '%02d  %s' % (i, title), font=font, fill=(255, 225, 120))
    draw.text((x + 8, y + 228), '%.0fs  %s' % (dur, (b.get('camera') or '')[:22]),
              font=font_s, fill=(170, 176, 186))

dst = 'D:/zlyun/Toonflow/本地视频工作台/剧本/断臂真相·黑猿/对照/新片EP1_26镜总览.png'
canvas.save(dst)
print('OK', dst, canvas.size, os.path.getsize(dst) // 1024, 'KB')
