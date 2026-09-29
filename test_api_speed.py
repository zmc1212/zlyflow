import time, requests
urls = [
    "http://127.0.0.1:7865/api/health",
    "http://127.0.0.1:7865/api/library",
    "http://127.0.0.1:7865/api/modes",
    "http://127.0.0.1:7865/api/director/projects"
]
for url in urls:
    start = time.monotonic()
    try:
        r = requests.get(url, timeout=5)
        print(f"GET {url}: {r.status_code} ({(time.monotonic() - start)*1000:.1f}ms)")
    except Exception as e:
        print(f"GET {url}: {e}")
