import time, requests
start = time.monotonic()
try:
    r = requests.get('http://127.0.0.1:7865/api/health', timeout=5)
    print(f"Health Time: {(time.monotonic() - start)*1000:.0f}ms")
except Exception as e:
    print(e)
