import sys, os
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('import { useEffect, useMemo, useRef, useState } from "react"', 'import { useEffect, useMemo, useRef, useState, memo } from "react"')
content = content.replace('React.memo', 'memo')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
