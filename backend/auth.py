# -*- coding: utf-8 -*-
"""
认证 + 速率限制：
- JWT token 认证
- 用户注册/登录
- 基于 slowapi 的速率限制
- 基于角色的权限控制（admin/user）
"""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

import config
from logger import get_logger
from session_store import session_store

logger = get_logger(__name__)

# JWT 配置（从环境变量读取，有默认值）
JWT_SECRET = os.environ.get("JWT_SECRET", "character_agent_secret_change_me_in_production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

# 速率限制配置
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
RATE_LIMIT_GENERATE_PER_HOUR = int(os.environ.get("RATE_LIMIT_GENERATE_PER_HOUR", "20"))


# ==================== 请求/响应模型 ====================
class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str


# ==================== JWT 工具 ====================
security = HTTPBearer(auto_error=False)


def _create_jwt(payload: dict) -> str:
    """创建 JWT token（简化版，不依赖 pyjwt）"""
    import base64
    import hmac

    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    # exp 必须放在 payload（claims）中，不能放在 header
    payload_with_exp = {
        **payload,
        "exp": (datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()
    }
    header_b64 = base64.urlsafe_b64encode(
        json.dumps(header, separators=(",", ":")).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload_with_exp, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{signing_input}.{sig_b64}"


def _verify_jwt(token: str) -> Optional[dict]:
    """验证 JWT token，返回 payload 或 None"""
    import base64
    import hmac

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        signing_input = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
        if not hmac.compare_digest(expected_sig_b64, parts[2]):
            return None
        # 解码 payload
        padding = "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        # 检查过期
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ==================== 依赖注入 ====================
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """获取当前用户。

    v2.2：登录注册已下线。无 token / 无效 token / 用户不存在 一律返回匿名用户；
    不再抛 401。所有需要登录态的接口不再使用 require_login。
    """
    if credentials is not None:
        payload = _verify_jwt(credentials.credentials)
        if payload is not None:
            user = session_store.get_user(payload.get("user_id", ""))
            if user is not None:
                return user
    return {"user_id": "anonymous", "username": "匿名用户", "role": "admin"}


# v2.2 兼容性：保留函数名，等价于 get_current_user（永远通过）
require_login = get_current_user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求管理员权限（v2.2 起永远通过）"""
    return user


# ==================== 速率限制（简单实现） ====================
class RateLimiter:
    """基于内存的滑动窗口速率限制器"""

    def __init__(self):
        self._requests: dict = {}  # key -> [timestamps]
        self._lock = __import__("threading").Lock()

    def check(self, key: str, max_count: int, window_seconds: int) -> bool:
        """检查是否超过限制，返回 True 表示允许"""
        now = time.time()
        with self._lock:
            if key not in self._requests:
                self._requests[key] = []
            # 清理过期记录
            self._requests[key] = [
                t for t in self._requests[key] if t > now - window_seconds]
            if len(self._requests[key]) >= max_count:
                return False
            self._requests[key].append(now)
            return True


rate_limiter = RateLimiter()


def rate_limit(max_per_minute: int = RATE_LIMIT_PER_MINUTE):
    """速率限制装饰器（v2.2 起按客户端 IP 限流，不再依赖 user_id）"""
    async def dependency(request: Request, user: dict = Depends(get_current_user)):
        client_ip = request.client.host if request.client else "unknown"
        key = f"ip:{client_ip}"
        if not rate_limiter.check(key, max_per_minute, 60):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁，每分钟限 {max_per_minute} 次")
        return user
    return dependency


def rate_limit_require_login(max_per_minute: int = RATE_LIMIT_PER_MINUTE):
    """v2.2 兼容性：等价于 rate_limit（不再要求登录），保留函数名给 server.py 现有调用。
    关键操作的限流键改为按 client_ip 区分，不再需要 user_id。
    """
    return rate_limit(max_per_minute)
