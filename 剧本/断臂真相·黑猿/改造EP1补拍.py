# -*- coding: utf-8 -*-
"""第 1 集补拍改造：
1) 清空 5 个坏镜的成片（2 弹额头情绪错 / 6 推到刀刃 / 7 推到底 / 8 跨两档 / 15 推到手部特写）
2) 在「给全桌看」与「全桌爆笑」之间插入「全场静」和「香克斯愣住」两个叙事镜
3) 修掉跨两档的机位描述
未出的 16-24 镜保留原样，只补拍不重排语义。
"""
import sys, json, secrets
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'
STYLE = ('ONE PIECE 原作动画设定稿风格，2D 赛璐璐平涂，中粗黑描线收边，'
         '硬边两层阴影，高饱和平涂色块，夸张透视，非写实、非3D、无胶片颗粒，')

# 要重新生成的镜（sequence）
REDO = [2, 6, 7, 8, 15]

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,data_json from ai_project_episodes where project_id=%s and episode_num=1", (PID,))
row = cur.fetchone()
d = json.loads(row['data_json'])
beats = d['beats']

CHAR_MAP, PROP_MAP = {}, {}
for b in beats:
    for n, i in zip(b.get('characters') or [], b.get('character_ids') or []):
        CHAR_MAP.setdefault(n, i)
    for n, i in zip(b.get('props') or [], b.get('prop_ids') or []):
        PROP_MAP.setdefault(n, i)
CHAR_MAP.setdefault('路飞', 'ast-a2ef997fb1db')
CHAR_MAP.setdefault('香克斯', 'ast-81ee7b290699')
print('角色:', CHAR_MAP)


def make(ref, title, action, camera, audio, dur, chars):
    b = dict(ref)
    b['id'] = 'beat-' + secrets.token_hex(6)
    b['heading'] = ''
    b['kind'] = 'action'
    b['speaker'] = ''
    b['dialogue'] = ''
    b['action'] = action
    b['camera'] = camera
    b['audio'] = audio
    b['characters'] = chars
    b['character_ids'] = [CHAR_MAP[n] for n in chars if n in CHAR_MAP]
    b['visual_prompt'] = STYLE + action + '，定机位单动作，落幅保持主体可辨认'
    b['sketch_prompt'] = b['visual_prompt']
    b['sketch_url'] = None
    b['render_url'] = None
    b['video_url'] = None
    b['upscaled_video_url'] = None
    b['video_prompt_zh'] = ''
    b['video_duration'] = str(dur)
    b['status'] = 'draft'
    b['_title'] = title
    for k in ('h3_prompt', 'h3_prompt_source', 'h3_prompt_input_signature',
              'timestamped_zh_prompt', 'authored_en_valid'):
        b.pop(k, None)
    return b


out = []
for b in beats:
    seq = b['sequence']
    title = b['heading'].split('（')[0].strip()
    b['_title'] = title

    # 修跨两档的机位
    if seq == 2:
        b['camera'] = '中近景，固定，从香克斯侧后带路飞正脸，5 秒'
        b['action'] = ('香克斯弯下腰，右手食指弹在路飞额头上，路飞脑袋向后一仰、'
                       '双手捂住额头，眉毛拧起来、嘴角往下撇，眼睛瞪回去。')
    if seq == 8:
        b['camera'] = '中近景 → 中景，拉远，从路飞脸到半张桌，5 秒匀速'
    if seq == 6:
        b['camera'] = '近景，固定，手与展开的小刀，5 秒'
    if seq == 7:
        b['camera'] = '中近景，固定，路飞上半身与左脸，5 秒'
        b['action'] = ('路飞把刀刃按在左脸颧骨上，斜着往下拉出一道血线，'
                       '血珠顺着脸颊淌到下巴，他咧开嘴笑，眼睛一直睁着。')
    if seq == 15:
        b['camera'] = '中近景，固定，两人上半身与相扣的手，5 秒'

    # 清空坏镜成片，让它们进入补拍队列
    if seq in REDO:
        b['video_url'] = None
        b['render_url'] = None
        b['upscaled_video_url'] = None
        b['status'] = 'draft'
        for k in ('h3_prompt', 'h3_prompt_source', 'h3_prompt_input_signature',
                  'timestamped_zh_prompt'):
            b.pop(k, None)

    out.append(b)

    # 镜8「给全桌看」之后：插「全场静」
    if seq == 8:
        out.append(make(b, '全场静',
            '整间酒馆定住，长桌旁的人手里举着杯子停在半空，没有人说话，只有杯里的酒轻轻晃。',
            '全景，固定，酒馆内正中，3 秒', '人声骤停、杯壁轻响、木梁吱呀', 3,
            ['香克斯', '贝克曼']))
        out.append(make(b, '香克斯愣住',
            '香克斯的手停在吧台上，眉毛慢慢抬起来，嘴角那点笑还没收住，眼睛先认真了。',
            '中近景，固定，香克斯正面，2 秒', '呼吸声、远处的海风', 2, ['香克斯']))

# 重排
t = 0.0
for i, b in enumerate(out, 1):
    b['sequence'] = i
    b['story_shot'] = i
    dd = float(b.get('video_duration') or 5)
    ti = b.pop('_title')
    b['heading'] = f"{ti}（{int(t)}-{int(t + dd)}秒） · {b.get('scene','')} · {b.get('camera','')}"
    t += dd

d['beats'] = out
cur.execute("update ai_project_episodes set data_json=%s, shots_count=%s where id=%s",
            (json.dumps(d, ensure_ascii=False), len(out), row['id']))
c.commit()

print(f'\nEP1: {len(beats)} 镜 -> {len(out)} 镜，总时长 {t:.0f} 秒')
print('待补拍：')
for b in out:
    if not (b.get('video_url') or b.get('render_url')):
        print(f"  镜{b['sequence']:2d}  {b['video_duration']:>2}s  {b['heading'].split('·')[0].strip()}")
c.close()
