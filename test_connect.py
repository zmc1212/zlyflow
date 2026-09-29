import time, os, sys
sys.path.append(os.getcwd())
from backend.app.db import MysqlDatabase, mysql_settings_from_env_or_docs
db = MysqlDatabase(mysql_settings_from_env_or_docs())
for i in range(5):
    start = time.monotonic()
    raw = db._connect()
    raw.close()
    print(f"Connect Run {i+1}: {(time.monotonic() - start)*1000:.0f}ms")
