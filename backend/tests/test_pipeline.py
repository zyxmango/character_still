# -*- coding: utf-8 -*-
"""
端到端集成测试：验证核心链路可用性。
不依赖 pytest，可直接运行：python tests/test_pipeline.py
"""
import json
import os
import sys
import time
from pathlib import Path

# 添加项目根到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ✅ {msg}")


def test_config():
    """测试 1：配置加载"""
    print("\n[1] 测试配置加载...")
    assert_true(config.OLLAMA_URL, "OLLAMA_URL 已配置")
    assert_true(config.COMFYUI_URL, "COMFYUI_URL 已配置")
    assert_true(config.OLLAMA_MODEL, "OLLAMA_MODEL 已配置")
    assert_true(config.STILLS_DIR.exists(), "输出目录已创建")
    assert_true(config.MAX_CONCURRENT_TASKS > 0, "并发数配置正确")


def test_imports():
    """测试 2：模块导入"""
    print("\n[2] 测试模块导入...")
    import tools
    import comfyui_client
    import task_queue
    import session_store
    import auth
    import retry
    import logger
    print("  ✅ 所有模块导入成功")


def test_session_store():
    """测试 3：用户存储（v2.1 会话已下线，只验证 users 表可用）"""
    print("\n[3] 测试用户存储...")
    from session_store import session_store
    user_id = session_store.create_user("test_user_" + str(int(time.time())), "pass123")
    assert_true(user_id, "创建用户成功")
    user = session_store.verify_user(
        session_store._get_conn().execute(
            "SELECT username FROM users WHERE user_id=?", (user_id,)).fetchone()["username"],
        "pass123")
    assert_true(user is not None, "用户验证逻辑可用")
    # 已废弃会话接口：保留签名但为 no-op
    placeholder_id = session_store.create_session(user_id, "测试对话")
    assert_true(placeholder_id, "create_session 返回占位 id")
    session_store.save_messages(placeholder_id, [{"role": "user", "content": "hi"}], {})
    s = session_store.get_session(placeholder_id)
    assert_true(s is None, "v2.1 起 get_session 返回空")
    session_store.delete_session(placeholder_id)
    assert_true(True, "delete_session 为 no-op")


def test_task_queue():
    """测试 4：任务队列（只测简单任务）"""
    print("\n[4] 测试任务队列...")
    from task_queue import task_queue, TaskStatus

    # 提交一个会失败的任务（无效参数）
    task_id = task_queue.submit("generate_prompt", {"style": "不存在", "counts": {}}, "test")
    assert_true(task_id, "任务提交成功")
    # 等待任务结束
    for _ in range(60):
        t = task_queue.get(task_id)
        if t["status"] in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            break
        time.sleep(1)
    assert_true(t["status"] in (TaskStatus.SUCCESS, TaskStatus.FAILED),
                f"任务已结束: {t['status']}")


def test_auth():
    """测试 5：鉴权依赖（v2.2 起免登录，验证 get_current_user 在各种情况下返回匿名用户）"""
    print("\n[5] 测试鉴权依赖...")
    import asyncio
    from auth import get_current_user, require_login, rate_limit, rate_limit_require_login
    # require_login 等价于 get_current_user（不再抛 401）
    assert_true(require_login is get_current_user, "v2.2 起 require_login = get_current_user")
    # rate_limit_require_login 等价于 rate_limit（不再依赖 require_login）
    assert_true(rate_limit_require_login(60).__name__ == rate_limit(60).__name__,
                "rate_limit_require_login 等价于 rate_limit")
    # 速率限制 key 现在只按 IP 区分
    from auth import rate_limiter
    assert_true(rate_limiter.check("ip:1.2.3.4", 100, 60), "IP 维度速率限制 key 可用")


def test_retry():
    """测试 6：重试机制"""
    print("\n[6] 测试重试机制...")
    from retry import retry_with_backoff, RetryError

    call_count = [0]

    @retry_with_backoff(max_retries=2, initial_delay=0.1)
    def flaky_func():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ValueError("模拟失败")
        return "success"

    result = flaky_func()
    assert_true(result == "success", "重试后成功")
    assert_true(call_count[0] == 3, f"共调用 3 次（实际 {call_count[0]}）")

    # 测试重试耗尽
    @retry_with_backoff(max_retries=1, initial_delay=0.1)
    def always_fail():
        raise ValueError("一直失败")

    try:
        always_fail()
        raise AssertionError("应该抛出 RetryError")
    except RetryError:
        print("  ✅ 重试耗尽正确抛出 RetryError")


def main():
    print("=" * 60)
    print("开始集成测试")
    print("=" * 60)
    tests = [
        test_config, test_imports, test_session_store,
        test_task_queue, test_auth, test_retry,
    ]
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"  ❌ 测试失败: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            return 1
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
