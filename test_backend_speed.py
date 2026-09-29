import time
import urllib.request
import json

start = time.time()
try:
    req = urllib.request.Request("http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4/workshop", headers={'Authorization': 'Bearer test'})
    with urllib.request.urlopen(req) as response:
        data = response.read()
    print(f"workshop took {time.time() - start:.2f}s, size: {len(data)} bytes")
except Exception as e:
    print(f"workshop failed: {e}")

start = time.time()
try:
    req = urllib.request.Request("http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4", headers={'Authorization': 'Bearer test'})
    with urllib.request.urlopen(req) as response:
        data = response.read()
    print(f"detail took {time.time() - start:.2f}s, size: {len(data)} bytes")
except Exception as e:
    print(f"detail failed: {e}")

