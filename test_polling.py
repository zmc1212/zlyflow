import time, requests
start = time.monotonic()
r = requests.get('http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4/production?mode=director', timeout=5)
print(f"Production: {r.status_code} - {(time.monotonic() - start)*1000:.0f}ms")

start = time.monotonic()
r = requests.get('http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4/workshop', timeout=5)
print(f"Workshop: {r.status_code} - {(time.monotonic() - start)*1000:.0f}ms")

start = time.monotonic()
r = requests.get('http://127.0.0.1:7865/api/projects/proj-0f9c8015281149f0/episodes/ep-4d89a8df80a4', timeout=5)
print(f"Detail: {r.status_code} - {(time.monotonic() - start)*1000:.0f}ms")
