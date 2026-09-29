import sys, os
sys.path.append(os.getcwd())
from backend.app.db import open_database
from backend.app.comfy_provider import ComfyProviderService
db = open_database()
from backend.app.storage import JobStore
store = JobStore(db)
svc = ComfyProviderService(store, 'http://127.0.0.1:8188')
print('URL:', svc.current_url())
