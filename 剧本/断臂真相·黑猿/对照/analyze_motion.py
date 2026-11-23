# -*- coding: utf-8 -*-
"""抽帧量化：判断成片是「一图+微动效」还是真有镜头运动。
用法: python analyze_motion.py <video.mp4> [标签]
输出: 每 0.4s 抽一帧算相邻帧平均像素差(mean abs diff)、构图位移(相位相关偏移)、
      并把四帧拼成联系表存盘。
"""
import sys, os, subprocess, json
import numpy as np

def ffprobe(path):
    out = subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height,r_frame_rate,nb_frames,duration',
        '-of','json',path], capture_output=True, text=True).stdout
    return json.loads(out)['streams'][0]

def read_frame(path, t):
    p = subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',path,'-frames:v','1',
        '-f','rawvideo','-pix_fmt','gray','-'], capture_output=True)
    return p.stdout

def main():
    path = sys.argv[1]
    tag = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(os.path.basename(path))[0]
    info = ffprobe(path)
    w, h = int(info['width']), int(info['height'])
    dur = float(info.get('duration') or 0)
    print(f'文件 {os.path.basename(path)}  {w}x{h}  {dur:.1f}s  fps={info["r_frame_rate"]}')

    step = 0.4
    ts = []
    t = 0.1
    frames = []
    while t < dur - 0.1:
        raw = read_frame(path, round(t, 2))
        if len(raw) == w*h:
            frames.append(np.frombuffer(raw, dtype=np.uint8).reshape(h, w).astype(np.float32))
            ts.append(round(t, 2))
        t += step
    print(f'抽帧 {len(frames)} 张')

    diffs = []
    for i in range(1, len(frames)):
        d = np.abs(frames[i] - frames[i-1]).mean()
        diffs.append(d)
    diffs = np.array(diffs)

    # 构图位移：用 cv2 相位相关估全局平移
    shifts = []
    try:
        import cv2
        for i in range(1, len(frames)):
            a = frames[i-1].astype(np.uint8)
            b = frames[i].astype(np.uint8)
            (dx, dy), resp = cv2.phaseCorrelate(np.float32(a), np.float32(b))
            shifts.append((round(float(dx),2), round(float(dy),2), round(float(resp),3)))
    except Exception as e:
        print('相位相关不可用:', e)

    print()
    print(f'帧差均值 {diffs.mean():.2f}  中位 {np.median(diffs):.2f}  最大 {diffs.max():.2f}  最小 {diffs.min():.2f}')
    if shifts:
        mag = [ (dx**2+dy**2)**0.5 for dx,dy,_ in shifts ]
        moved = sum(1 for m in mag if m >= 1.0)
        print(f'构图位移(px) 均值 {np.mean(mag):.2f}  中位 {np.median(mag):.2f}  最大 {max(mag):.2f}')
        print(f'超过 1px 位移的相邻帧对: {moved}/{len(mag)}  ({100.0*moved/max(1,len(mag)):.0f}%)')
        for (dx,dy,r),m in list(zip(shifts,mag))[:40]:
            print(f'   {m:.2f}px  dx={dx} dy={dy} resp={r}')

    # 判定
    med_shift = np.median([ (dx**2+dy**2)**0.5 for dx,dy,_ in shifts ]) if shifts else 0
    verdict = []
    if diffs.mean() < 6: verdict.append('画面几乎不动（PPT 风险高）')
    elif diffs.mean() < 15: verdict.append('只有轻微纹理蠕动（接近 PPT）')
    else: verdict.append('画面变化明显')
    if med_shift < 0.8: verdict.append('构图固定，缺镜头运动')
    elif med_shift < 3: verdict.append('有真实镜头运动')
    else: verdict.append('运动幅度大（正常跟移/推拉）')
    print()
    print('判定:', ' / '.join(verdict))

if __name__ == '__main__':
    main()
