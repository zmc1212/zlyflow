import time, requests

def test_url(url):
    start = time.monotonic()
    try:
        r = requests.get(url, timeout=10)
        print(f"{url} -> {r.status_code} in {(time.monotonic() - start)*1000:.0f}ms")
    except Exception as e:
        print(f"{url} -> {e}")

test_url('http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4')
test_url('http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4/workshop')
