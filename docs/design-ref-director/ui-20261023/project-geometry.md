# 元素几何偏差

偏差是 CSS 像素，不是还原率；布局可测量不证明未遮挡、字体正确或交互可用。

| 区域 | 状态 | Δx | Δy | Δ宽 | Δ高 |
| --- | --- | --- | --- | --- | --- |
| project-header | measured | -12.0 | 0.0 | 12.0 | 0.0 |
| content-panel | measured | 0.0 | -6.0 | -1.0 | -1.0 |
| canvas | reference_only | — | — | — | — |
| surface | reference_only | — | — | — | — |

## 相对前轮的最大绝对偏差

| 区域 | 前轮 | 本轮 | 变化 |
| --- | --- | --- | --- |
| project-header | 12.0 | 12.0 | unchanged |
| content-panel | 6.0 | 6.0 | unchanged |
| canvas | None | None | unavailable |
| surface | None | None | unavailable |
