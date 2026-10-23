# -*- coding: utf-8 -*-
"""
用户持久化：基于 SQLite。

历史背景：
- v2.0 曾同时承担「对话会话」+「用户」存储
- v2.1 移除 Agent 对话框后，对话会话下线
- v2.2 移除登录注册后，users 表也不再被任何路由写入/读取

保留 users / sessions 表的 schema 与兼容方法以避免历史 SQLite 数据迁移时被外部脚本
hard-fail。如需彻底清理可运行 `DROP TABLE sessions;` 与 `DROP TABLE users;`。
"""
import hashlib
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import config


class SessionStore:
    """用户存储单例（兼容旧名）"""

    _instance: Optional["SessionStore"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self.db_path = str(config.OUTPUT_DIR / "sessions.db")
        config.ensure_dirs()
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            # users 表：登录 / JWT 用户主体
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    role TEXT DEFAULT 'user'
                )
            """)
            # sessions 表：保留旧 schema 以兼容历史数据（不再写入）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    messages TEXT NOT NULL,
                    agent_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user
                ON sessions(user_id, updated_at DESC)
            """)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------- 用户管理（保留）----------------
    def create_user(self, username: str, password: str, role: str = "user") -> str:
        user_id = str(uuid.uuid4())[:12]
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, created_at, role) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, username, password_hash, now, role))
            conn.commit()
        return user_id

    def verify_user(self, username: str, password: str) -> Optional[dict]:
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username=? AND password_hash=?",
                (username, password_hash)).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    # ---------------- 会话（已废弃，保留以防被外部脚本调用）----------------
    def create_session(self, user_id: str, title: str = "新对话") -> str:
        """已废弃：Agent 对话框移除后会话不再有业务用途；保留方法返回占位 session_id。"""
        return str(uuid.uuid4())[:12]

    def get_session(self, session_id: str) -> Optional[dict]:
        return None

    def list_sessions(self, user_id: str, limit: int = 20) -> list:
        return []

    def save_messages(self, session_id: str, messages: list, agent_state: dict):
        return None

    def rename_session(self, session_id: str, title: str):
        return None

    def delete_session(self, session_id: str):
        return None


# 全局单例
session_store = SessionStore()
