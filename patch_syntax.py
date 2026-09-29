import sys, os
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the syntax error: ) = [
content = content.replace("], [actionProps, openMediaPreview]) = [", "], [actionProps, openMediaPreview])")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
