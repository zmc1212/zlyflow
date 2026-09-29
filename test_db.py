import time, os, sys
sys.path.append(os.getcwd())
from backend.app.db import open_database
from backend.app.storage import JobStore
db = open_database()
store = JobStore(db)

for i in range(5):
    start = time.monotonic()
    store.get_grs_settings()
    store.get_comfy_settings()
    store.get_grs_settings()
    print(f"DB Run {i+1}: {(time.monotonic() - start)*1000:.0f}ms")
