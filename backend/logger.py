# -*- coding: utf-8 -*-
"""
结构化日志 + 错误监控：
- JSON 格式日志，带 trace_id
- 每个请求一个 trace_id，贯穿全链路
- 错误自动记录到日志文件
- 统一的 logger 配置
"""
import json
import logging
import logging.handlers
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import config


class JSONFormatter(logging.Formatter):
    """JSON 格式日志 formatter"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # 添加 trace_id（如果存在）
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        # 添加额外字段
        for key, value in record.__dict__.items():
            if key not in ("args", "asctime", "created", "exc_info", "exc_text",
                           "filename", "funcName", "levelname", "levelno", "lineno",
                           "module", "msecs", "message", "msg", "name", "pathname",
                           "process", "processName", "relativeCreated", "thread",
                           "threadName", "trace_id"):
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)
        # 异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def setup_logging():
    """初始化全局日志配置（幂等：重复调用不会重复添加 handler）"""
    config.ensure_dirs()
    log_dir = config.OUTPUT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # 幂等保护：如果已经配置过 handler，直接返回，避免重复打印
    if getattr(root_logger, "_setup_done", False):
        return
    # 清理可能已存在的 handler（防御性）
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    # 控制台 handler（人类可读）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))

    # 文件 handler（JSON 格式，带轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024,
        backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())

    # 错误文件 handler
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log", maxBytes=5 * 1024 * 1024,
        backupCount=3, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger._setup_done = True  # 标记已配置


def get_trace_id() -> str:
    """生成新的 trace_id"""
    return str(uuid.uuid4())[:8]


class TraceLogger:
    """带 trace_id 的 logger 包装"""

    def __init__(self, name: str, trace_id: str = None):
        self.logger = logging.getLogger(name)
        self.trace_id = trace_id or get_trace_id()

    def _log(self, level: int, msg: str, **kwargs):
        extra = {"trace_id": self.trace_id, **kwargs}
        self.logger.log(level, msg, extra=extra)

    def debug(self, msg: str, **kwargs):
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._log(logging.ERROR, msg, **kwargs)

    def exception(self, msg: str, **kwargs):
        extra = {"trace_id": self.trace_id, **kwargs}
        self.logger.exception(msg, extra=extra)


# 模块级别便捷函数
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
