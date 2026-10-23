# -*- coding: utf-8 -*-
"""
轻量级异步任务队列：基于 ThreadPoolExecutor + SQLite 持久化。
功能等价于 Celery，但无需额外 Redis/RabbitMQ 服务依赖，适合单机部署。

特性：
- 异步提交长耗时任务（出图/修图/全流程），立即返回 task_id
- 任务状态持久化到 SQLite，重启后仍可查询
- 支持取消、查询状态、查询历史
- 任务进度实时写入 DB，前端可轮询
- 并发度可配置，避免 ComfyUI 过载
"""
import json
import queue as _queue
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import config


# ==================== 任务状态枚举 ====================
class TaskStatus:
    PENDING = "pending"      # 已提交，排队中
    RUNNING = "running"      # 执行中
    SUCCESS = "success"      # 成功
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消


# ==================== 事件订阅器（线程安全 pub/sub）====================
class TaskEventBroker:
    """任务事件代理：工作线程发布事件，WebSocket 消费者订阅。
    使用 threading.Lock 保护订阅者列表；事件通过 asyncio.Queue 跨线程投递。
    订阅者以 (queue, loop) 元组登记，loop 用于 call_soon_threadsafe。
    """

    def __init__(self):
        self._subscribers: List[tuple] = []  # 元素: (asyncio.Queue, asyncio.AbstractEventLoop)
        self._sync_subscribers: List[_queue.Queue] = []  # 同步订阅（供工作线程消费）
        self._lock = threading.Lock()

    def subscribe(self, queue, loop):
        with self._lock:
            self._subscribers.append((queue, loop))

    def unsubscribe(self, queue):
        with self._lock:
            self._subscribers = [(q, l) for (q, l) in self._subscribers if q is not queue]

    def subscribe_sync(self) -> "_queue.Queue":
        """同步订阅：返回 threading.Queue，供工作线程（非 asyncio）消费事件。"""
        q: _queue.Queue = _queue.Queue()
        with self._lock:
            self._sync_subscribers.append(q)
        return q

    def unsubscribe_sync(self, q):
        with self._lock:
            self._sync_subscribers = [s for s in self._sync_subscribers if s is not q]

    def publish(self, event: dict):
        """从工作线程调用：把事件投递到所有订阅者（asyncio + 同步）。"""
        with self._lock:
            subs = list(self._subscribers)
            sync_subs = list(self._sync_subscribers)
        # 异步订阅（WebSocket 消费者）
        for q, loop in subs:
            try:
                if loop is None or loop.is_closed():
                    continue
                loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass
        # 同步订阅（任务执行线程消费事件，用于阻塞式 API 等待）
        for q in sync_subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass


# 全局事件代理
event_broker = TaskEventBroker()


# ==================== 任务队列 ====================
class TaskQueue:
    """单例任务队列：线程池执行 + SQLite 持久化"""

    _instance: Optional["TaskQueue"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self.db_path = str(config.OUTPUT_DIR / "tasks.db")
        config.ensure_dirs()
        self._init_db()
        # 工作线程数：ComfyUI 同时跑有限任务，默认 2
        self.max_workers = config.MAX_CONCURRENT_TASKS
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="worker")
        self._futures: Dict[str, Future] = {}
        # 启动时把上次未完成的任务标记为失败（进程已被杀）
        self._mark_interrupted_tasks()

    # ---------------- 事件发射 ----------------
    def _emit(self, task_id: str, event_type: str, payload: Optional[dict] = None):
        """发射任务事件到所有订阅者"""
        event = {
            "task_id": task_id,
            "type": event_type,
            "ts": datetime.now().isoformat(),
        }
        if payload:
            event.update(payload)
        event_broker.publish(event)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    args TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    progress TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    user_id TEXT
                )
            """)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _mark_interrupted_tasks(self):
        """进程重启时，把上次 running/pending 的任务标记为 failed"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tasks SET status=?, error=?, finished_at=? "
                "WHERE status IN (?, ?)",
                (TaskStatus.FAILED, "进程重启中断", datetime.now().isoformat(),
                 TaskStatus.RUNNING, TaskStatus.PENDING))
            conn.commit()

    # ---------------- 对外 API ----------------
    def submit(self, task_type: str, args: dict, user_id: str = "default",
               func: Optional[Callable] = None) -> str:
        """提交任务，立即返回 task_id"""
        task_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, task_type, args, status, progress, created_at, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, task_type, json.dumps(args, ensure_ascii=False),
                 TaskStatus.PENDING, json.dumps([], ensure_ascii=False), now, user_id))
            conn.commit()

        # 解析实际执行函数
        if func is None:
            func = self._resolve_func(task_type)

        future = self.executor.submit(self._run, task_id, func, args)
        self._futures[task_id] = future

        # 事件：任务已提交（pending）
        self._emit(task_id, "task_submitted", {
            "task_type": task_type,
            "status": TaskStatus.PENDING,
            "user_id": user_id,
            "created_at": now,
        })
        return task_id

    def _resolve_func(self, task_type: str) -> Callable:
        """根据任务类型返回执行函数（来自 tools.py，无 Agent 依赖）"""
        from tools import TOOL_REGISTRY
        if task_type not in TOOL_REGISTRY:
            raise ValueError(f"未知任务类型: {task_type}")
        return TOOL_REGISTRY[task_type][0]

    def _run(self, task_id: str, func: Callable, args: dict):
        """实际执行任务（在工作线程中）"""
        # 标记为 running
        started_at = datetime.now().isoformat()
        self._update(task_id, status=TaskStatus.RUNNING, started_at=started_at)
        # 事件：任务开始执行
        self._emit(task_id, "task_running", {
            "status": TaskStatus.RUNNING,
            "started_at": started_at,
        })

        try:
            # func 是生成器函数，逐步消费并记录进度
            result = None
            progress_list = self._get_progress(task_id)
            # 把 task_id 注入 args，让工具能按任务归档图片
            if isinstance(args, dict):
                args.setdefault("task_id", task_id)
            for ev in func(args):
                if ev.get("type") == "_result":
                    result = ev["result"]
                else:
                    progress_list.append(ev)
                    self._update(task_id, progress=json.dumps(
                        progress_list, ensure_ascii=False))
                    # 事件：进度更新（只发最新一条，避免前端处理整个列表）
                    self._emit(task_id, "task_progress", {
                        "status": TaskStatus.RUNNING,
                        "progress_item": ev,
                        "progress_count": len(progress_list),
                    })

            finished_at = datetime.now().isoformat()
            self._update(task_id, status=TaskStatus.SUCCESS,
                         result=json.dumps(result, ensure_ascii=False),
                         finished_at=finished_at)
            # 事件：任务成功
            self._emit(task_id, "task_success", {
                "status": TaskStatus.SUCCESS,
                "result": result,
                "finished_at": finished_at,
            })

        except Exception as e:
            finished_at = datetime.now().isoformat()
            self._update(task_id, status=TaskStatus.FAILED,
                         error=str(e), finished_at=finished_at)
            # 事件：任务失败
            self._emit(task_id, "task_failed", {
                "status": TaskStatus.FAILED,
                "error": str(e),
                "finished_at": finished_at,
            })

    def cancel(self, task_id: str) -> bool:
        """取消任务（仅对 pending 有效；running 的无法真正杀线程）"""
        task = self.get(task_id)
        if not task:
            return False
        if task["status"] == TaskStatus.PENDING:
            future = self._futures.get(task_id)
            if future and future.cancel():
                finished_at = datetime.now().isoformat()
                self._update(task_id, status=TaskStatus.CANCELLED,
                             finished_at=finished_at)
                self._emit(task_id, "task_cancelled", {
                    "status": TaskStatus.CANCELLED,
                    "finished_at": finished_at,
                })
                return True
        elif task["status"] == TaskStatus.RUNNING:
            # running 任务无法真正中断 Python 线程，但标记为 cancelled
            finished_at = datetime.now().isoformat()
            self._update(task_id, status=TaskStatus.CANCELLED,
                         error="用户取消（运行中任务可能仍会完成）",
                         finished_at=finished_at)
            self._emit(task_id, "task_cancelled", {
                "status": TaskStatus.CANCELLED,
                "error": "用户取消（运行中任务可能仍会完成）",
                "finished_at": finished_at,
            })
            return True
        return False

    def get(self, task_id: str) -> Optional[dict]:
        """查询单个任务状态"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_tasks(self, user_id: str = None, limit: int = 50) -> list:
        """列出任务（可按用户过滤）"""
        with self._get_conn() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _get_progress(self, task_id: str) -> list:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT progress FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row and row["progress"]:
            return json.loads(row["progress"])
        return []

    def _update(self, task_id: str, **fields):
        """更新任务字段"""
        if not fields:
            return
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [task_id]
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE task_id=?", values)
            conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("args", "result", "progress"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d


# 全局单例
task_queue = TaskQueue()
