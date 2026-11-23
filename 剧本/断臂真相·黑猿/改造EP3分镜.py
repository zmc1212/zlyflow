# -*- coding: utf-8 -*-
"""第 3 集分镜改造：13 镜 -> 19 镜
按第 1、2 集验证过的「讲故事」配方：
  默认固定机位（唯一一次推近只跨一档）、补「静」与反应镜、爆发镜压到 2-3 秒。
"""
import sys, json, os, copy, uuid, re
sys.path.insert(0, 'D:/zlyun/Toonflow/本地视频工作台/backend')
import pymysql

DB = dict(host='192.168.10.200', port=3307, user='ai_media_app',
          password='YLb9LkRmIn38zGFldjazVHBd', database='ai-media',
          charset='utf8mb4', autocommit=True, connect_timeout=8, read_timeout=20)
PID = 'proj-dd6ca6baac23473b'
BAK = 'D:/zlyun/Toonflow/本地视频工作台/剧本/断臂真相·黑猿/对照/EP3_data_backup.json'
STYLE = ('ONE PIECE 原作动画设定稿风格，2D 赛璐璐平涂，中粗黑描线收边，硬边两层阴影，'
         '高饱和平涂色块，夸张透视，非写实、非3D、无胶片颗粒，')

c = pymysql.connect(**DB)
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("select id,data_json from ai_project_episodes "
            "where project_id=%s and episode_num=3", (PID,))
r = cur.fetchone()
EPID = r['id']
data = json.loads(r['data_json'])
orig = data['beats']
open(BAK, 'w', encoding='utf-8').write(r['data_json'])
print('已备份 EP3 原始 %d 镜 -> %s' % (len(orig), BAK))

# 资产映射（从原始 13 镜 + 资产表兜底）
CHAR, SCENE, PROP = {}, {}, {}
for b in orig:
    for n, i in zip(b.get('characters') or [], b.get('character_ids') or []):
        CHAR.setdefault(n, i)
    if b.get('scene') and b.get('scene_id'):
        SCENE.setdefault(b['scene'], b['scene_id'])
    for n, i in zip(b.get('props') or [], b.get('prop_ids') or []):
        PROP.setdefault(n, i)
cur.execute("select name,kind,id from ai_project_assets where project_id=%s", (PID,))
for a in cur.fetchall():
    n = a['name']
    if n not in CHAR and a['kind'] == 'character':
        CHAR[n] = a['id']
    if n not in SCENE and a['kind'] == 'scene':
        SCENE[n] = a['id']
    if n not in PROP and a['kind'] in ('prop', 'props', 'item'):
        PROP[n] = a['id']

SNOW = '艾尔巴夫·雪原·闪前'
SEA = '近海·风暴海面·黄昏'
UNDER = '浅海·水下·冷青'
STERN = '红色海贼船·船尾·清晨'

# (标题, 参考原镜序号, 场景, 时长, 机位, 动作, 台词, 说话人, 音效, 角色, 道具, 视觉描述, kind)
SHOTS = [
    ('雪原', 1, SNOW, 5, '大全景，固定，风雪纵深，5 秒',
     '暴雪里，一个直立的身影从雪雾深处一步步走出来，脚印在雪地上拉成一串。',
     '', '黑猿', '风雪、踩雪的闷响', ['黑猿'], ['草帽'],
     '艾尔巴夫暴雪雪原，直立身影从雪雾深处一步步走来，雪地脚印拉成一串，黑色巨树剪影，冷灰高对比', 'action'),

    ('站定', 2, SNOW, 4, '全景，固定，正面，4 秒',
     '黑猿在雪原中央停下，漆黑的长发和长尾被风掀向一侧，肩头云絮状的黑色毛发翻卷。',
     '', '黑猿', '风声压过踩雪声', ['黑猿'], ['草帽'],
     '雪原中央黑猿站定，长发长尾被风掀向一侧，肩头黑毛翻卷，黑色巨树剪影', 'action'),

    ('金瞳', 3, SNOW, 3, '中近景，固定，平视，3 秒',
     '黑猿慢慢抬起头，琥珀金色的圆瞳在风雪里亮起来，瞳孔缩了一下。',
     '', '黑猿', '风雪忽然变轻', ['黑猿'], ['草帽'],
     '黑猿抬头，琥珀金色圆瞳在风雪里亮起，瞳孔收缩，中近景保持正脸可读，冷灰背景', 'action'),

    ('风雪忽然静', 1, SNOW, 3, '大全景，固定，与开场同机位，3 秒',
     '风雪声压下去，黑猿站住不动，只有雪落在肩头积成一线。',
     '', '黑猿', '风声骤降、只剩细雪', ['黑猿'], ['草帽'],
     '与开场完全相同的大全景构图，黑猿一动不动站在雪原中央，雪落在肩头积成白线，画面极静', 'action'),

    ('裂开的帽檐', 4, SNOW, 4, '近景，固定，侧后方带帽檐，4 秒',
     '黑猿抬起手碰了一下背后草帽的帽檐，帽檐边缘裂开一道细缝，一缕黑气从缝里冒出来。',
     '', '黑猿', '布料裂开的细响', ['黑猿'], ['草帽'],
     '黑猿侧后方近景，手触碰背后草帽帽檐，边缘裂开细缝，一缕黑气从缝里冒出，手与帽檐同框可读', 'action'),

    ('闪回·水面暗红', 5, SEA, 4, '特写，固定，水面俯拍，4 秒',
     '水面上一团暗红从画面边缘慢慢扩开，颜色比上一集更浓，边缘清晰泛黑，黑丝在水里游动。',
     '', '香克斯', '闷住的水声', ['香克斯'], ['红色披风'],
     '海面俯拍特写，暗红从画面边缘慢慢扩开，边缘泛黑，黑丝在水里游动，冷青海面', 'action'),

    ('闪回·心跳停止', 6, UNDER, 4, '中景，固定，水下平视，4 秒',
     '水下的路飞身体忽然抽了一下，四肢软下去，嘴里冒出的最后一串气泡往上飘走。',
     '', '路飞', '水下闷响、心跳停了', ['路飞'], ['草帽'],
     '水下中景平视，路飞身体抽动后四肢软下去，最后一串气泡上飘，冷青色，全身可读', 'action'),

    ('静·气泡散尽', 6, UNDER, 2, '中景，固定，与上一镜同机位，2 秒',
     '最后一串气泡没了，水里彻底安静，路飞的头发缓缓沉下去。',
     '', '路飞', '完全静音', ['路飞'], ['草帽'],
     '与上一镜完全相同的水下中景构图，气泡散尽，路飞头发缓缓下沉，画面静止，冷青色', 'action'),

    ('闪回·破水', 7, SEA, 3, '全景 → 中景，推近，低机位仰拍，3 秒',
     '水里炸开一大片白浪，一个通体漆黑的瘦长身影从水下立起来，草帽挂在背后。',
     '', '黑猿', '破水的巨响', ['黑猿'], ['草帽'],
     '海面炸开白浪，通体漆黑的瘦长身影从水下立起，草帽挂在背后，低机位仰拍，冷青与白浪高对比', 'action'),

    ('闪回·咬', 8, SEA, 3, '近景，固定，用斗篷和浪遮挡咬合点，3 秒',
     '黑猿扑到香克斯身上，头一低，獠牙咬进他左小臂内侧，香克斯的手在半空僵住。',
     '', '香克斯', '压抑的兽吼、浪声', ['黑猿', '香克斯'], ['红色披风'],
     '近景，红色斗篷与白浪挡在两人之间，黑猿低头，香克斯的手僵在半空，不直接露出咬合点', 'action'),

    ('静·白浪悬停', 8, SEA, 2, '近景，固定，与上一镜同机位，2 秒',
     '白浪停在半空不落，两个人影都不动，只剩斗篷一角在风里翻。',
     '', '香克斯', '完全静音', ['黑猿', '香克斯'], ['红色披风'],
     '与上一镜相同构图，白浪悬在半空，两人不动，只有红色斗篷一角翻起，画面静止', 'action'),

    ('闪回·螺旋纹亮', 9, SEA, 3, '特写，固定，左小臂内侧，3 秒',
     '香克斯左小臂内侧的螺旋纹一圈圈亮起来，光沿着纹路往外走，到断口处断掉。',
     '', '香克斯', '低沉的共鸣', ['香克斯'], ['浅海印记'],
     '左小臂内侧特写，螺旋纹一圈圈亮起，光沿纹路外走到断口处断掉，冷青底光', 'action'),

    ('闪回·按回去', 10, SEA, 6, '中景，固定，俯拍，6 秒',
     '香克斯抬起右手按住黑猿的后脑，把它整个按回水里，水面炸开一圈白浪。',
     '香克斯：「戻れ、ルフィ。」', '香克斯', '水面合拢、压抑的兽吼', ['香克斯', '黑猿'], ['草帽'],
     '俯拍中景，香克斯抬右手按住黑猿后脑把它按回水里，水面炸开一圈白浪，两人同框', 'dialogue'),

    ('反应·空袖管', 10, SEA, 2, '近景，固定，平视香克斯正脸，2 秒',
     '香克斯低头看自己左边空掉的袖管，眼睛没眨，嘴唇抿成一条线。',
     '', '香克斯', '只剩风声', ['香克斯'], ['红色披风'],
     '香克斯正脸近景，视线落向左侧空掉的袖管，眼睛没眨，嘴唇抿成一条线，表情克制', 'action'),

    ('闪回·扣帽', 11, SEA, 6, '中景，固定，从香克斯侧后带路飞正脸，6 秒',
     '黑毛从路飞身上一点点褪尽，变回七岁的孩子，香克斯把草帽扣在他头顶。',
     '香克斯：「お前だったのか。」', '香克斯', '浪声退远', ['香克斯', '路飞'], ['草帽'],
     '中景固定，香克斯侧后带路飞正脸，黑毛褪尽变回七岁孩子，草帽扣在头顶，两人同框', 'dialogue'),

    ('反应·路飞睁眼', 11, SEA, 2, '近景，固定，路飞正脸，2 秒',
     '路飞睁开眼，只觉得冷，看看自己的手，什么都没想起来。',
     '', '路飞', '一声吸鼻子', ['路飞'], ['草帽'],
     '路飞正脸近景，刚睁眼，茫然低头看自己的手，草帽阴影落在脸上，什么都没想起来的表情', 'action'),

    ('船尾·缝', 12, STERN, 5, '中近景，固定，从背影带双手与草帽，5 秒',
     '香克斯坐在船尾，把一缕黑发一样的细线缠进草帽内侧的帽檐，用针脚一针一针压住。',
     '', '香克斯', '针穿过草编的细响', ['香克斯'], ['草帽', '缆绳'],
     '船尾清晨，香克斯背影中近景，双手把一缕黑发般细线缠进草帽内侧帽檐，一针一针压住，手与帽同框', 'action'),

    ('静·最后一针', 12, STERN, 2, '特写，固定，手与帽檐，2 秒',
     '最后一针压住，手停在那儿不动，海面很静。',
     '', '香克斯', '完全静音', ['香克斯'], ['草帽'],
     '手与草帽帽檐特写，最后一针压住，手停住不动，清晨冷光，画面静止', 'action'),

    ('低吼', 13, SNOW, 6, '大全景，固定，与开场同机位，6 秒',
     '黑猿在雪原上仰起头，张开嘴发出一声长吼，喉咙深处的气浪把身前的雪掀起来。',
     '画外音：「この十秒を、誰も覚えていない。」', '黑猿', '长吼、风雪、极远处的回声',
     ['黑猿'], ['草帽'],
     '与开场完全相同的大全景构图，黑猿仰头张嘴长吼，气浪把身前积雪掀起，黑色巨树剪影，冷灰暴雪', 'dialogue'),
]

new_beats = []
t = 0
for idx, (title, src_i, scene, dur, camera, action, dialogue, speaker, audio,
          chars, props, visual, kind) in enumerate(SHOTS, 1):
    base = copy.deepcopy(orig[src_i - 1])
    base['id'] = 'beat-' + uuid.uuid4().hex[:12]
    base['sequence'] = idx
    base['story_shot'] = idx
    base['kind'] = kind
    base['heading'] = '%s（%d-%d秒） · %s · %s' % (title, t, t + dur, scene, camera)
    base['speaker'] = speaker
    base['dialogue'] = dialogue
    base['action'] = action
    base['camera'] = camera
    base['audio'] = audio
    base['characters'] = list(chars)
    base['character_ids'] = [CHAR.get(n, '') for n in chars]
    base['scene'] = scene
    base['scene_id'] = SCENE.get(scene, '')
    base['props'] = list(props)
    base['prop_ids'] = [PROP.get(n, '') for n in props]
    base['visual_prompt'] = STYLE + visual
    base['sketch_prompt'] = STYLE + visual
    base['video_prompt_zh'] = '%s 运镜：%s 声音：%s' % (action, camera, audio)
    base['video_duration'] = str(dur)
    base['status'] = 'draft'
    for k in ('sketch_url', 'render_url', 'video_url', 'upscaled_video_url', 'h3_prompt'):
        base[k] = None
    new_beats.append(base)
    t += dur

data['beats'] = new_beats
payload = json.dumps(data, ensure_ascii=False)
print('待写入 data_json %d 字符' % len(payload))
import time
for attempt in range(1, 6):
    try:
        cur.execute("update ai_project_episodes set data_json=%s, shots_count=%s where id=%s",
                    (payload, len(new_beats), EPID))
        print('写入成功（第 %d 次尝试，影响行 %d）' % (attempt, cur.rowcount))
        break
    except Exception as e:
        print('第 %d 次写入失败: %s' % (attempt, str(e)[:120]))
        if attempt == 5:
            raise
        time.sleep(4)
print('写入 EP3：%d 镜，总时长 %d 秒' % (len(new_beats), t))

# 校验
print('\n==== 校验 ====')
bad = [i for i, b in enumerate(new_beats, 1) if not b['scene_id'] or
       '' in b['character_ids'] or '' in b['prop_ids']]
print('资产绑定缺失镜:', bad or '无')
lock = sum(1 for b in new_beats if '固定' in b['camera'])
print('固定机位 %d / 运镜 %d（共 %d）' % (lock, len(new_beats) - lock, len(new_beats)))
for i, b in enumerate(new_beats, 1):
    if not re.search(r'[\u4e00-\u9fff]', b['dialogue']) and b['dialogue']:
        print('  !! 镜%d 台词无汉字，可能卡校验: %s' % (i, b['dialogue']))
    if '大特写' in b['camera']:
        print('  !! 镜%d 仍用大特写' % i)
print('时长分布:', [b['video_duration'] for b in new_beats])
c.close()
