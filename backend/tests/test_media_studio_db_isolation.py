import unittest
from unittest.mock import patch

from backend.app.media_studio import db


class MediaStudioDbIsolationTests(unittest.TestCase):
    @patch("backend.app.media_studio.db.pymysql.connect")
    def test_unittest_cannot_open_a_real_media_database_connection(self, connect):
        with self.assertRaisesRegex(RuntimeError, "隔离测试禁止"):
            db._connect_mysql()
        connect.assert_not_called()

    @patch("backend.app.media_studio.db.pymysql.connect")
    @patch("backend.app.media_studio.db.get_mysql_config", return_value={"host": "db.example", "port": 3306, "user": "test", "password": "synthetic", "database": "studio"})
    @patch("backend.app.db.is_isolated_sqlite_runtime", return_value=False)
    def test_server_connection_keeps_its_existing_configuration(self, isolated, config, connect):
        self.assertIs(connect.return_value, db._connect_mysql(autocommit=False))
        self.assertFalse(connect.call_args.kwargs["autocommit"])
