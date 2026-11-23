# -*- coding: utf-8 -*-
"""第 2 集分镜改造：补「静」和反应镜头，拆掉多动作长镜，修掉跨两档的运镜。
原 24 镜 -> 30 镜。
"""
import sys, json, secrets
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.125', port=3306, user='root', password='123456',
          database='ai-media', charset='utf8mb4')
PID = 'proj-dd6ca6baac23473b'

STYLE = ('ONE PIECE 原作动画设定稿风格，2D 赛璐璐平涂，中粗黑描线收边，'
         '硬边两层阴影，高饱和平涂色块，夸张透视，非写实、非3D、无胶片颗粒，')


def newid():
    return 'beat-' + secrets.token_hex(6)


def make_beat(ref, title, action, camera, audio, dur, chars, scene_key=None, props_key=None,
              visual=None, speaker=''):
    """从参照 beat 继承资产绑定，生成新 beat。"""
    b = {
        'id': newid(),
        'sequence': 0,
        'kind': 'dialogue' if speaker else 'action',
        'heading': '',
        'speaker': speaker,
        'dialogue': '',
        'action': action,
        'camera': camera,
        'audio': audio,
        'characters': chars,
        'character_ids': [CHAR_MAP[n] for n in chars if n in CHAR_MAP],
        'scene': scene_key or ref['scene'],
        'scene_id': SCENE_MAP.get(scene_key or ref['scene']) or ref.get('scene_id'),
        'props': (props_key if props_key is not None else ref.get('props') or []),
        'prop_ids': ([PROP_MAP[p] for p in props_key if p in PROP_MAP]
                     if props_key is not None else (ref.get('prop_ids') or [])),
        'visual_prompt': STYLE + (visual or action) + '，定机位单动作，落幅保持主体可辨认，不出现血腥',
        'sketch_prompt': STYLE + (visual or action) + '，定机位单动作，落幅保持主体可辨认，不出现血腥',
        'sketch_url': None, 'render_url': None, 'video_url': None, 'upscaled_video_url': None,
        'video_prompt_zh': '',
        'video_duration': str(dur),
        'status': 'draft',
        'story_shot': 0,
        'source_episode_id': ref.get('source_episode_id'),
    }
    b['sketch_prompt'] = b['visual_prompt']
    b['_title'] = title
    return b


c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,data_json from ai_project_episodes where project_id=%s and episode_num=2", (PID,))
row = cur.fetchone()
ep_id, data = row['id'], json.loads(row['data_json'])
beats = data['beats']

# 资产映射（从全片 beats 收集，再用已知 id 兜底）
CHAR_MAP = {'近海之王': 'ast-3fa5026c4b79', '玛琪诺': 'ast-7fce496384c5',
            '香克斯': 'ast-81ee7b290699', '路飞': 'ast-a2ef997fb1db',
            '黑猿': 'ast-e4d040e9ebb8', '西格': 'ast-f47ebc86c2b1',
            '贝克曼': 'ast-fbe28b089150'}
PROP_MAP = {'草帽': 'ast-364b79347f9c', '红色披风': 'ast-b64a282978ea',
            '小刀': 'ast-dfcb39aa29bd', '缆绳': 'ast-d0e18d21e388',
            '小木船': 'ast-aab1d77ca571', '木桶': 'ast-6351499c140c'}
SCENE_MAP = {}
for b in beats:
    for n, i in zip(b.get('characters') or [], b.get('character_ids') or []):
        CHAR_MAP.setdefault(n, i)
    if b.get('scene') and b.get('scene_id'):
        SCENE_MAP.setdefault(b['scene'], b['scene_id'])
    for n, i in zip(b.get('props') or [], b.get('prop_ids') or []):
        PROP_MAP.setdefault(n, i)
print('角色映射', CHAR_MAP)
print('场景映射', SCENE_MAP)

for b in beats:
    t = b['heading'].split('（')[0].strip()
    b['_title'] = t

out = []
for b in beats:
    seq_now = b['sequence']

    # 镜16「瞪视」：原来大特写→中景拉远跨两档，改成固定大特写
    if seq_now == 16:
        b['camera'] = '大特写，固定，眼睛与断臂一侧的侧脸，5 秒'
        b['action'] = ('香克斯的眼睛占满画面，瞳孔没有收缩，雨水顺着眉骨流进眼眶，'
                       '他一次都没有眨眼，视线穿过镜头盯着画面外的近海之王。')

    out.append(b)

    # 镜15「咬合」后：插入「静」
    if seq_now == 15:
        out.append(make_beat(
            b, '静', '海面突然静下来，翻起的白浪缓缓回落，斗篷边缘一滴血落进水里，在水面荡开一圈红。',
            '中景，固定，水面与斗篷下摆，3 秒', '雨声停了、只剩浪在退、一滴水落进海面', 3,
            ['香克斯', '近海之王'], props_key=['红色披风'],
            visual='海面死寂，白浪回落，黑色斗篷下摆边缘一滴血落进水里荡开红圈'))

    # 镜16「瞪视」后：插入「咬牙」反应
    if seq_now == 16:
        out.append(make_beat(
            b, '咬牙', '香克斯的侧脸占满画面，牙关咬到腮帮鼓起，太阳穴青筋绷起，汗混着雨从额角滑到下颌。',
            '近景，固定，侧脸四分之三，2 秒', '牙齿咬紧的摩擦、粗重呼吸、雨点打在斗篷上', 2,
            ['香克斯'], props_key=[],
            visual='红发男人侧脸近景，牙关咬紧、腮帮鼓起、额头青筋与汗，雨水顺下颌流下'))

    # 镜19「走上沙滩」后：插入「看袖管」
    if seq_now == 19:
        out.append(make_beat(
            b, '看袖管', '路飞抬头，视线落到香克斯左边的空袖管上，先是没有反应，半秒后瞳孔缩了一下，嘴张开却没出声。',
            '中近景，固定，路飞正面偏侧，2 秒', '海浪、脚步停住、呼吸声', 2,
            ['路飞'], props_key=[],
            visual='草帽男孩抬头，视线落在画面外的空袖管上，瞳孔收缩，嘴巴张开无声音'))

    # 镜20「抓住空袖管」：8 秒多动作长镜 -> 拆成三镜
    if seq_now == 20:
        out.pop()  # 移除原镜
        out.append(make_beat(
            b, '探进袖管', '路飞的手指摸到空袖管的开口，指尖探进去，里面什么也没有，手指在布里撑开又落下。',
            '特写，固定，手指与空袖管，2 秒', '布料被撑开的窸窣、海浪拍岸', 2,
            ['路飞', '香克斯'], props_key=[],
            visual='一只小孩的手探进垂下的空袖管口，指尖在布料里撑开又落下，袖管空空'))
        out.append(make_beat(
            b, '嘴唇在抖', '路飞的脸占满画面，眼睛睁得很大，眼泪没有掉下来，下嘴唇在抖，鼻翼一张一合。',
            '大特写，固定，正面，2 秒', '压抑的抽气、海风', 2,
            ['路飞'], props_key=[],
            visual='草帽男孩正面大特写，眼睛睁大、眼眶有水光但不掉泪、下嘴唇发抖'))
        out.append(make_beat(
            b, '埋进袖管', '路飞把整张脸埋进那条空袖管里，肩膀开始一抽一抽地抖。',
            '中近景，固定，侧后方，3 秒', '闷住的哭声、布料摩擦、海', 3,
            ['路飞', '香克斯'], props_key=[],
            visual='男孩把脸埋进大人垂下的空袖管，肩膀抽动，侧后方机位'))

    # 镜21「扣草帽」前：插入「草帽停在半空」
    if seq_now == 21:
        out.pop()  # 先摘掉本镜，插入停顿后再放回
        out.append(make_beat(
            b, '草帽停在半空', '香克斯用右手托起那顶草帽，停在路飞头顶上方，手没有落下去，草帽在风里轻轻晃。',
            '中近景，固定，低角度仰拍，2 秒', '风、草帽边沿轻响、远处的海', 2,
            ['香克斯', '路飞'], props_key=['草帽'],
            visual='低角度仰拍，红发男人单手托草帽停在男孩头顶上方悬住不落，草帽边沿在风里晃'))
        out.append(b)

# 重排 sequence / story_shot / 时间码 / heading
t = 0.0
for i, b in enumerate(out, 1):
    b['sequence'] = i
    b['story_shot'] = i
    d = float(b.get('video_duration') or 5)
    title = b.pop('_title', b['heading'].split('（')[0].strip())
    b['heading'] = f"{title}（{int(t)}-{int(t + d)}秒） · {b.get('scene','')} · {b.get('camera','')}"
    # 提示词全部作废，等用新模板重新生成
    for k in ('h3_prompt', 'h3_prompt_source', 'h3_prompt_input_signature',
              'timestamped_zh_prompt', 'authored_en_valid', 'video_prompt_zh'):
        b.pop(k, None)
    b['status'] = 'draft'
    b['video_url'] = None
    b['render_url'] = None
    t += d

data['beats'] = out
data.pop('episode_video_url', None)
data.pop('episode_video_job_id', None)
data.pop('episode_video_source', None)

cur.execute("update ai_project_episodes set data_json=%s, shots_count=%s where id=%s",
            (json.dumps(data, ensure_ascii=False), len(out), ep_id))
c.commit()
print(f'\n改造完成：{len(beats)} 镜 -> {len(out)} 镜，总时长 {t:.0f} 秒')
for b in out:
    print(f"  {b['sequence']:2d} {b['video_duration']:>2}s  {b['heading'][:52]}")
c.close()
