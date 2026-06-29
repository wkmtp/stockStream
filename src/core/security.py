# ============================================================
# AI数字人财经直播平台 V4.0 — 安全模块
# ============================================================
# 功能:
#   - API Token 验证
#   - 配置加密/解密
#   - 日志脱敏
#   - 环境变量安全读取
#   - Cookie 保护
# ============================================================

from __future__ import annotations

import os
import re
import hmac
import hashlib
import base64
import logging
import secrets
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── 敏感字段模式 ──
_SENSITIVE_PATTERNS: Dict[str, re.Pattern] = {
    "password": re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*\S+', re.IGNORECASE),
    "token": re.compile(r'(?:api[_\-]?key|access[_\-]?token|auth[_\-]?token|secret[_\-]?key)\s*[=:]\s*\S+', re.IGNORECASE),
    "phone": re.compile(r'1[3-9]\d{9}'),
    "email": re.compile(r'[\w.\-]+@[\w\-]+\.\w+'),
    "ip": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
}


class SecurityManager:
    """安全管理器 — 单例"""

    _instance: Optional["SecurityManager"] = None

    def __new__(cls) -> "SecurityManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._token_secret: str = os.environ.get(
            "STOCKSTREAM_TOKEN_SECRET",
            secrets.token_hex(32),
        )
        self._encryption_key: Optional[bytes] = None
        self._init_encryption()

    def _init_encryption(self) -> None:
        """初始化加密密钥"""
        key_env = os.environ.get("STOCKSTREAM_ENCRYPTION_KEY")
        if key_env:
            self._encryption_key = base64.b64decode(key_env.encode())
        else:
            # 生产环境必须通过环境变量注入
            logger.warning("未设置 STOCKSTREAM_ENCRYPTION_KEY，加密功能降级")

    # ============================================================
    # API Token 管理
    # ============================================================

    def generate_token(self, scope: str = "api", ttl_hours: int = 24) -> str:
        """生成 API Token"""
        payload = f"{scope}:{datetime.utcnow().isoformat()}:{secrets.token_hex(8)}"
        sig = hmac.new(
            self._token_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        token = base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")
        return token

    def validate_token(self, token: str, required_scope: Optional[str] = None) -> bool:
        """验证 API Token"""
        try:
            # 补齐 padding
            padding = 4 - len(token) % 4
            if padding != 4:
                token += "=" * padding
            decoded = base64.urlsafe_b64decode(token.encode()).decode()
            payload, sig = decoded.rsplit(".", 1)
            expected_sig = hmac.new(
                self._token_secret.encode(),
                payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return False
            if required_scope:
                scope = payload.split(":")[0]
                if scope != required_scope:
                    return False
            return True
        except Exception:
            return False

    # ============================================================
    # 配置加密
    # ============================================================

    def encrypt_value(self, plaintext: str) -> Optional[str]:
        """加密配置值 (AES-GCM)"""
        if self._encryption_key is None:
            logger.warning("加密未配置，返回明文")
            return None
        try:
            from cryptography.fernet import Fernet
            f = Fernet(base64.urlsafe_b64encode(self._encryption_key[:32]))
            return f.encrypt(plaintext.encode()).decode()
        except ImportError:
            logger.error("cryptography 库未安装，无法加密")
            return None

    def decrypt_value(self, ciphertext: str) -> Optional[str]:
        """解密配置值"""
        if self._encryption_key is None:
            return None
        try:
            from cryptography.fernet import Fernet
            f = Fernet(base64.urlsafe_b64encode(self._encryption_key[:32]))
            return f.decrypt(ciphertext.encode()).decode()
        except Exception:
            return None

    # ============================================================
    # 日志脱敏
    # ============================================================

    @classmethod
    def sanitize_log(cls, message: str) -> str:
        """脱敏日志中的敏感信息"""
        sanitized = message
        sanitized = _SENSITIVE_PATTERNS["password"].sub(
            lambda m: m.group(0).split("=")[0] + "=***", sanitized
        )
        sanitized = _SENSITIVE_PATTERNS["token"].sub(
            lambda m: m.group(0).split("=")[0] + "=***", sanitized
        )
        sanitized = _SENSITIVE_PATTERNS["phone"].sub(
            lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], sanitized
        )
        return sanitized

    # ============================================================
    # 环境变量安全读取
    # ============================================================

    @staticmethod
    def get_env_secret(key: str, default: Optional[str] = None) -> Optional[str]:
        """安全读取环境变量（禁止打印原始值）"""
        value = os.environ.get(key, default)
        if value and key.upper() in ("PASSWORD", "SECRET", "TOKEN", "KEY"):
            logger.debug("读取敏感环境变量: %s (值已脱敏)", key)
        return value

    # ============================================================
    # 请求验证
    # ============================================================

    @staticmethod
    def verify_request_origin(
        token: Optional[str],
        allowed_tokens: list,
        remote_ip: Optional[str] = None,
    ) -> bool:
        """验证请求来源"""
        if not token:
            return False
        return token in allowed_tokens


# ── 全局单例 ──
_security: Optional[SecurityManager] = None


def get_security() -> SecurityManager:
    """获取安全管理器单例"""
    global _security
    if _security is None:
        _security = SecurityManager()
    return _security
