from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.db import is_unreachable_mysql_error, parse_storage_config, rewrite_sql


class StorageConfigTests(unittest.TestCase):
    def test_parse_docs_storage_config(self) -> None:
        parsed = parse_storage_config(Path("docs") / "存储配置.md")
        mysql = parsed["mysql"]
        self.assertEqual(mysql["host"], "110.42.216.180")
        self.assertEqual(mysql["port"], 3307)
        self.assertEqual(mysql["database"], "ai-media")
        self.assertEqual(mysql["user"], "root")
        self.assertTrue(mysql["password"])

    def test_mysql_rewrites_insert_or_ignore(self) -> None:
        sql = rewrite_sql("INSERT OR IGNORE INTO jobs (id) VALUES (?)", "mysql")
        self.assertEqual(sql, "INSERT IGNORE INTO jobs (id) VALUES (%s)")

    def test_mysql_timeout_is_treated_as_unreachable(self) -> None:
        self.assertTrue(is_unreachable_mysql_error(TimeoutError("timed out")))
        try:
            import pymysql
        except ImportError:
            return
        self.assertTrue(is_unreachable_mysql_error(pymysql.err.OperationalError(2003, "Can't connect")))
        self.assertFalse(is_unreachable_mysql_error(pymysql.err.OperationalError(1045, "Access denied")))

    def test_sqlite_begin_immediate_is_recognized(self) -> None:
        from backend.app.db import _SQLITE_BEGIN

        self.assertTrue(_SQLITE_BEGIN.match("BEGIN IMMEDIATE"))
        self.assertTrue(_SQLITE_BEGIN.match("begin exclusive"))
        self.assertFalse(_SQLITE_BEGIN.match("BEGIN TRANSACTION FROM jobs"))
