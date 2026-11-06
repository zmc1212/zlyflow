"""Face selection and spatial gates, independent of the GPU model."""
from __future__ import annotations

import math


def choose_face(landmarks, expected, span, *, first=False, expected_width=None):
    """Stay on the selected face; never choose an arbitrary visible replacement."""
    candidates = []
    for index, points in enumerate(landmarks):
        if len(points) != 5 or not all(math.isfinite(float(v)) for p in points for v in p):
            continue
        center = (sum(float(p[0]) for p in points) / 5, sum(float(p[1]) for p in points) / 5)
        width = max(float(p[0]) for p in points) - min(float(p[0]) for p in points)
        distance = math.hypot(center[0] - expected[0], center[1] - expected[1])
        if expected_width is not None and not .45 <= width / expected_width <= 1.8:
            continue
        limit = max(width * .95, span * .06) if first else max((expected_width or width) * 1.8, span * .12)
        if width > 0 and distance <= limit:
            candidates.append((distance, index))
    return min(candidates)[1] if candidates else None


def frame_windows(valid, length, overlap):
    if not 0 <= overlap < length:
        raise ValueError("时序重叠必须小于处理窗口")
    index = 0
    while index < len(valid):
        if not valid[index]:
            index += 1
            continue
        end = index + 1
        while end < len(valid) and valid[end]:
            end += 1
        start = index
        while start < end:
            stop = min(start + length, end)
            yield start, stop
            if stop == end:
                break
            start = stop - overlap
        index = end
