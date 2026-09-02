from __future__ import annotations

"""Apply sql/*.sql files to the remote MySQL instance in docs/存储配置.md."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db import MysqlDatabase, SQL_DIR, mysql_settings_from_env_or_docs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_file", nargs="?", default="001_init_mysql.sql")
    args = parser.parse_args()
    path = Path(args.sql_file)
    if not path.is_file():
        path = SQL_DIR / args.sql_file
    sql = path.read_text(encoding="utf-8")
    mysql = MysqlDatabase(mysql_settings_from_env_or_docs())
    print(f"执行 {path} -> {mysql.config['host']}:{mysql.config['port']}/{mysql.config['database']}")
    with mysql.connection() as connection:
        connection.executescript(sql)
    print("远程 SQL 执行完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
