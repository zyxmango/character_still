# -*- coding: utf-8 -*-
"""
重试 + 降级：
- LLM 调用失败时指数退避重试
- ComfyUI 调用失败时重试
- 主模型不可用时降级到备用模型
- 统一的装饰器风格使用
"""
import functools
import time
from typing import Callable, List, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)


class RetryError(Exception):
    """重试耗尽"""
    pass


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Exception, ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    指数退避重试装饰器

    Args:
        max_retries: 最大重试次数（不含首次）
        initial_delay: 首次重试延迟（秒）
        max_delay: 最大延迟（秒）
        exceptions: 触发重试的异常类型
        on_retry: 重试回调 fn(attempt, exception, delay)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            f"重试耗尽: {func.__name__}, 已尝试 {attempt + 1} 次, 错误: {e}")
                        raise RetryError(
                            f"{func.__name__} 重试 {max_retries} 次后仍失败: {e}") from e
                    logger.warning(
                        f"第 {attempt + 1} 次重试 {func.__name__} (延迟 {delay:.1f}s): {e}")
                    if on_retry:
                        try:
                            on_retry(attempt + 1, e, delay)
                        except Exception:
                            pass
                    time.sleep(delay)
                    delay = min(delay * 2, max_delay)
        return wrapper
    return decorator


class ModelFallback:
    """
    模型降级：主模型不可用时切换到备用模型。

    用法:
        fallback = ModelFallback(["qwen3:32b", "qwen2.5:14b", "qwen2.5:7b"])
        model = fallback.get_available_model()
    """

    def __init__(self, models: List[str], check_func: Optional[Callable[[str], bool]] = None):
        self.models = models
        self.check_func = check_func or self._default_check

    @staticmethod
    def _default_check(model: str) -> bool:
        """默认检查模型是否可用（调 Ollama /api/tags）"""
        try:
            import requests
            resp = requests.get("http://localhost:11434/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = [m["name"] for m in resp.json().get("models", [])]
            # 精确匹配或前缀匹配（qwen3:32b 也匹配 qwen3:32b-instruct）
            return any(model == m or m.startswith(model.split(":")[0] + ":") for m in models)
        except Exception as e:
            logger.warning(f"检查模型 {model} 可用性失败: {e}")
            return False

    def get_available_model(self, verbose: bool = True) -> str:
        """返回第一个可用的模型。verbose=False 时不打印日志（避免每次新建 Agent 都刷屏）"""
        for model in self.models:
            if self.check_func(model):
                if verbose:
                    logger.info(f"使用模型: {model}")
                return model
        raise RetryError(f"所有模型均不可用: {self.models}")
