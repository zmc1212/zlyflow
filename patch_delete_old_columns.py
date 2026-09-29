import sys, os
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = -1
for i, line in enumerate(lines):
    if "], [actionProps, openMediaPreview])" in line:
        start_idx = i + 1
        break

if start_idx == -1:
    print("Could not find start_idx")
    sys.exit(1)

end_idx = -1
for i in range(start_idx, len(lines)):
    if "function getStatusTag" in lines[i]:
        # We want to delete up to the   ] just before this function
        # Let's search backwards from here
        for j in range(i-1, start_idx-1, -1):
            if lines[j].strip() == "]":
                end_idx = j + 1
                break
        break

if end_idx == -1:
    print("Could not find end_idx")
    sys.exit(1)

del lines[start_idx:end_idx]

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Deleted old columns array")
