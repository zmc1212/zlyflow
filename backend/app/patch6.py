import sys

with open("frontend/src/index.css", "r", encoding="utf-8") as f:
    content = f.read()

dragger_css = """
.director-asset-dragger .ant-upload-drag {
  border: none !important;
  background: transparent !important;
  padding: 0 !important;
  border-radius: 10px;
}
.director-asset-dragger .ant-upload-btn {
  padding: 0 !important;
}
"""

if "director-asset-dragger" not in content:
    content = content.replace(".director-character-visual,", dragger_css + "\n.director-character-visual,")
    with open("frontend/src/index.css", "w", encoding="utf-8") as f:
        f.write(content)
