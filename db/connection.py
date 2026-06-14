"""
SQLite 数据库连接管理
支持初始化 Schema、连接池获取、上下文管理器
"""

import sys
import sqlite3
import threading
from pathlib import Path
from contextlib import contextmanager

# 确保项目根目录在 Python Path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


class DatabaseManager:
    """
    SQLite 数据库管理器
    - 线程本地连接池
    - 自动执行 PRAGMA 优化
    - Schema 初始化
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH
        self._local = threading.local()
        self._ensure_db_dir()

    def _ensure_db_dir(self):
        """确保数据库文件所在目录存在"""
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

    @property
    def connection(self) -> sqlite3.Connection:
        """获取线程本地连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")       # Write-Ahead Logging
            conn.execute("PRAGMA foreign_keys=ON")         # 启用外键约束
            conn.execute("PRAGMA busy_timeout=5000")       # 忙等待 5s
            conn.execute("PRAGMA cache_size=-20000")       # 20MB 缓存
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def get_connection(self):
        """上下文管理器：自动 commit/rollback"""
        conn = self.connection
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def init_schema(self, schema_path: str = None):
        """
        初始化数据库 Schema
        从 db/schema.sql 读取 DDL 并执行
        """
        if schema_path is None:
            schema_path = Path(__file__).parent / "schema.sql"

        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            conn.executescript(schema_sql)

        print(f"[DB] Schema initialized from {schema_path}")

    def execute(self, sql: str, params: tuple = None) -> sqlite3.Cursor:
        """执行 SQL 语句"""
        conn = self.connection
        if params:
            return conn.execute(sql, params)
        return conn.execute(sql)

    def executemany(self, sql: str, params_list: list) -> sqlite3.Cursor:
        """批量执行 SQL 语句"""
        conn = self.connection
        return conn.executemany(sql, params_list)

    def fetch_one(self, sql: str, params: tuple = None) -> dict:
        """查询单行结果"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params) if params else conn.execute(sql)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = None) -> list[dict]:
        """查询多行结果"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params) if params else conn.execute(sql)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def insert_one(self, sql: str, params: tuple) -> int:
        """插入单行并返回 rowid"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def insert_many(self, sql: str, params_list: list):
        """批量插入"""
        with self.get_connection() as conn:
            conn.executemany(sql, params_list)

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        result = self.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return result is not None

    def table_row_count(self, table_name: str) -> int:
        """获取表行数"""
        result = self.fetch_one(f"SELECT COUNT(*) as cnt FROM {table_name}")
        return result["cnt"] if result else 0

    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# 全局数据库管理器单例
db = DatabaseManager()


if __name__ == "__main__":
    # 直接运行此文件则初始化数据库
    import sys
    if "--init" in sys.argv:
        db.init_schema()
        print("[DB] Database initialization complete.")
    else:
        print(f"[DB] Database path: {db.db_path}")
        print(f"[DB] Tables: {[t['name'] for t in db.fetch_all('SELECT name FROM sqlite_master WHERE type=\"table\"')]}")
