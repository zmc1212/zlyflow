import time, requests
start = time.monotonic()
try:
    requests.get('http://192.168.10.54:8188/system_stats', timeout=3)
    print("Success")
except Exception as e:
    print("Error:", e)
print(f"Time: {(time.monotonic() - start)*1000:.0f}ms")
