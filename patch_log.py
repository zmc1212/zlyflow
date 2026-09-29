import sys, os
path = "backend/app/request_log.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target1 = "await self.app(scope, replay, send_wrapper)"
repl1 = "import time\n        start_time = time.monotonic()\n        await self.app(scope, replay, send_wrapper)\n        duration_ms = int((time.monotonic() - start_time) * 1000)"
if target1 in content:
    content = content.replace(target1, repl1)

target2 = '\"status\": status_box.get(\"status\"),'
repl2 = '\"status\": status_box.get(\"status\"),\n                \"duration_ms\": duration_ms,'
if target2 in content:
    content = content.replace(target2, repl2)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
