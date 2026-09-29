import sys, os
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target1 = '<Drawer title="已采纳剧本" open={script} onClose={'
repl1 = '{script && <Drawer destroyOnClose title="已采纳剧本" open={script} onClose={'
if target1 in content:
    content = content.replace(target1, repl1)
else:
    print("target1 not found")

target2 = '历史视频"} · {m.id}</a>)}</Space>}]} /></Drawer>'
repl2 = '历史视频"} · {m.id}</a>)}</Space>}]} /></Drawer>}'
if target2 in content:
    content = content.replace(target2, repl2)
else:
    print("target2 not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
