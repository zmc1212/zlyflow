import sys

with open("frontend/src/index.css", "r", encoding="utf-8") as f:
    content = f.read()

# Replace object-fit
content = content.replace(
""".director-character-visual img,
.director-simple-asset-visual img {
  width: 100%;
  height: 180px;
  object-fit: contain;""",
""".director-character-visual img,
.director-simple-asset-visual img {
  width: 100%;
  height: 180px;
  object-fit: cover;"""
)

# Add chip overrides
chip_overrides = """
.director-character-visual .director-asset-status-chip,
.director-simple-asset-visual .director-asset-status-chip {
  box-shadow: 0 1px 4px rgba(0,0,0,0.12);
}
.director-character-visual .director-asset-status-chip.is-ready,
.director-simple-asset-visual .director-asset-status-chip.is-ready {
  background: #ecfdf5 !important;
  color: #059669 !important;
  border: 1px solid #a7f3d0 !important;
}
:root[data-theme="dark"] .director-character-visual .director-asset-status-chip.is-ready,
:root[data-theme="dark"] .director-simple-asset-visual .director-asset-status-chip.is-ready {
  background: #022c22 !important;
  color: #34d399 !important;
  border: 1px solid #065f46 !important;
}
"""

# Append to the end of the file
content += "\n" + chip_overrides

with open("frontend/src/index.css", "w", encoding="utf-8") as f:
    f.write(content)
