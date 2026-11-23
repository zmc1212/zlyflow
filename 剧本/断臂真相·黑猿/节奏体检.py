# -*- coding: utf-8 -*-
"""节奏体检：量化每镜 5 秒内部的「运动停止点」与「尾部冻结时长」。

对每个分镜 mp4：
  1. 每 0.4s 抽灰度帧，算相邻帧平均像素差 -> 运动曲线
  2. 冻结判定：相邻帧差 < 2.5（0-255 灰度）视为画面不动
  3. 尾部冻结：最后一个「动」的采样点到片尾的时间
  4. silencedetect 找最后一声人声/音效的结束点（裁剪时保住声音）

输出逐镜表格 + 对照/节奏体检.json
用法: python 节奏体检.py [EP1|EP2|EP3]   # 缺省全量
"""
import sys, os, json, subprocess
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, '对照')
EP_DIRS = {'EP1': '新片EP1', 'EP2': '新片EP2', 'EP3': '新片EP3'}
FREEZE = 2.5      # 帧差低于该值视为画面不动
STEP = 0.4        # 采样步长（秒）


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                          'stream=codec_type,duration', '-of', 'json', path],
                         capture_output=True, text=True).stdout
    d = json.loads(out)
    dur = 0.0
    has_audio = False
    for s in d['streams']:
        if s['codec_type'] == 'video':
            dur = float(s.get('duration') or 0)
        elif s['codec_type'] == 'audio':
            has_audio = True
    return dur, has_audio


def motion_curve(path, dur):
    w, h = 1344, 768
    ts, fs = [], []
    t = 0.0
    while t < dur - 0.05:
        p = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(round(t, 2)), '-i', path,
                            '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
                           capture_output=True)
        if len(p.stdout) == w * h:
            fs.append(np.frombuffer(p.stdout, dtype=np.uint8).reshape(h, w).astype(np.float32))
            ts.append(round(t, 2))
        t += STEP
    diffs = [float(np.abs(fs[i] - fs[i - 1]).mean()) for i in range(1, len(fs))]
    return ts, diffs


def last_sound(path):
    """silencedetect: 返回最后一段非静音的结束时刻（约等于声音收尾点）"""
    p = subprocess.run(['ffmpeg', '-v', 'info', '-i', path, '-af',
                        'silencedetect=noise=-38dB:d=0.4', '-f', 'null', '-'],
                       capture_output=True, text=True)
    ends = []
    for line in (p.stderr or '').splitlines():
        if 'silence_end' in line:
            try:
                ends.append(float(line.split('silence_end:')[1].split('|')[0].strip()))
            except ValueError:
                pass
    if not ends:
        return None  # 全程有声
    return ends[-1]


def scan(ep):
    folder = os.path.join(OUT_DIR, EP_DIRS[ep])
    rows = []
    names = sorted(f for f in os.listdir(folder)
                   if f.startswith(ep + '_') and f.endswith('.mp4'))
    for fn in names:
        path = os.path.join(folder, fn)
        dur, has_audio = probe(path)
        ts, diffs = motion_curve(path, dur)
        if not diffs:
            rows.append((fn, dur, 0, 0, 0, dur, None))
            continue
        # 运动曲线四等分均值（看运动是不是全压在前段）
        q = len(diffs) // 4 or 1
        quarters = [round(float(np.mean(diffs[i * q:(i + 1) * q])), 1) for i in range(4)]
        # 尾部冻结：最后一个差值 >= FREEZE 的采样点
        active_idx = [i for i, d in enumerate(diffs) if d >= FREEZE]
        if active_idx:
            last_active_t = ts[active_idx[-1] + 1]      # 最后一次运动发生处的下一采样
            tail_freeze = round(dur - last_active_t, 1)
        else:
            last_active_t = 0.0
            tail_freeze = round(dur, 1)
        # 最长连续冻结段
        longest = run = 0
        for d in diffs:
            run = run + STEP if d < FREEZE else 0.0
            longest = max(longest, run)
        snd = last_sound(path) if has_audio else None
        rows.append((fn, round(dur, 2), quarters, round(float(np.mean(diffs)), 1),
                     round(longest, 1), tail_freeze, snd))
    return rows


def main():
    eps = sys.argv[1:] or list(EP_DIRS)
    all_rows = {}
    print(f'冻结阈值 帧差<{FREEZE} | 采样步长 {STEP}s | 「尾部冻结」=最后一次画面运动到片尾\n')
    for ep in eps:
        rows = scan(ep)
        all_rows[ep] = [dict(seg=r[0], dur=r[1], quarters=r[2], motion=r[3],
                             longest_frozen=r[4], tail_freeze=r[5], sound_end=r[6])
                        for r in rows]
        print(f'=== {ep} ({len(rows)} 镜) ===')
        print(f"{'镜':<10}{'时长':>6}  {'运动Q1/Q2/Q3/Q4':>17}  {'均差':>6} {'最长冻结':>8} {'尾部冻结':>8} {'声音收尾':>8}")
        for fn, dur, quarters, mean_d, longest, tail, snd in rows:
            qs = '/'.join(str(x) for x in quarters) if isinstance(quarters, list) else '-'
            snd_s = f'{snd:.1f}s' if snd is not None else ('全程' if snd == -1 else '无')
            print(f"{fn:<10}{dur:>6.2f}  {qs:>17}  {mean_d:>6.1f} {longest:>7.1f}s {tail:>7.1f}s {snd_s:>8}")
        bad = [r for r in rows if (r[5] if len(r) > 5 else 0) >= 1.6]
        print(f'-> 尾部冻结 ≥1.6s 的镜头: {len(bad)}/{len(rows)}\n')

    with open(os.path.join(OUT_DIR, '节奏体检.json'), 'w', encoding='utf-8') as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=1)
    print('明细已存 对照/节奏体检.json')


if __name__ == '__main__':
    main()
