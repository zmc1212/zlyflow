import time, requests
for i in range(10):
    start = time.monotonic()
    try:
        requests.get('http://192.168.10.54:8188/system_stats', timeout=3)
        print(f"Ping {i+1}: {(time.monotonic() - start)*1000:.0f}ms")
    except Exception as e:
        print(f"Ping {i+1}: error {e}")
