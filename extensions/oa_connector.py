"""
extensions/oa_connector.py
企业 OA 系统对接模块。
"""
import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from agent_core.models import ApprovalStatus, SubmitResult

logger = logging.getLogger(__name__)


@dataclass
class OAConfig:
    """OA 系统对接配置"""

    api_url: str = ""
    auth_type: str = "bearer"  # bearer | basic | hmac
    auth_credentials: dict = field(default_factory=dict)
    field_mapping: dict = field(default_factory=dict)
    webhook_secret: str = ""
    polling_interval: int = 60
    use_webhook: bool = True
    submit_timeout: int = 30


class OAConnector:
    """OA 系统对接连接器。"""

    def __init__(self, config: OAConfig) -> None:
        self.config = config

    async def submit_voucher(self, voucher: dict) -> SubmitResult:
        """
        提交凭证到 OA 系统。

        返回:
        - success=True: 提交成功（若响应包含 approval_id 则一并返回）
        - success=False: 提交失败并返回错误原因
        """
        if not self.config.api_url:
            return SubmitResult(success=False, error="OA api_url 未配置")

        mapped_payload = self._map_fields(voucher)
        headers = self._build_auth_headers(mapped_payload)

        try:
            async with httpx.AsyncClient(timeout=self.config.submit_timeout) as client:
                response = await client.post(
                    self.config.api_url,
                    json=mapped_payload,
                    headers=headers,
                )
        except Exception as e:
            logger.error("OA 提交请求失败: %s", e)
            return SubmitResult(success=False, error=f"OA提交失败: {e}")

        if response.status_code >= 400:
            body = (response.text or "")[:300]
            logger.error("OA 提交返回错误 status=%s body=%s", response.status_code, body)
            return SubmitResult(
                success=False,
                error=f"OA提交失败: HTTP {response.status_code} {body}",
            )

        try:
            data = response.json() if response.content else {}
        except Exception:
            data = {}

        approval_id = self._extract_approval_id(data)
        return SubmitResult(success=True, approval_id=approval_id)

    async def handle_webhook(self, payload: dict, signature: str) -> Optional[ApprovalStatus]:
        """处理 OA 审批状态回调，并校验签名。"""
        if not self._verify_signature(payload, signature):
            logger.warning("Webhook 签名校验失败，拒绝请求")
            raise ValueError("Invalid webhook signature")

        status_str = payload.get("approval_status", "")
        try:
            status = ApprovalStatus(status_str)
        except ValueError:
            logger.error("未知的审批状态: %s", status_str)
            raise ValueError(f"Unknown approval status: {status_str}")

        logger.info(
            "Webhook 状态更新: approval_id=%s, status=%s",
            payload.get("approval_id"),
            status.value,
        )
        return status

    async def poll_status(self, approval_id: str) -> ApprovalStatus:
        """轮询模式查询审批状态（占位实现）。"""
        logger.info("轮询审批状态 approval_id=%s", approval_id)
        return ApprovalStatus.PENDING

    def _verify_signature(self, payload: dict, signature: str) -> bool:
        secret = self.config.webhook_secret.encode("utf-8")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def _build_auth_headers(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        auth_type = (self.config.auth_type or "").lower()
        creds = self.config.auth_credentials or {}

        if auth_type == "bearer":
            token = str(creds.get("token", ""))
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            username = str(creds.get("username", ""))
            password = str(creds.get("password", ""))
            if username or password:
                raw = f"{username}:{password}".encode("utf-8")
                headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("utf-8")
        elif auth_type == "hmac":
            secret = str(creds.get("secret", ""))
            key_id = str(creds.get("key_id", ""))
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            signature = hmac.new(
                secret.encode("utf-8"),
                body + timestamp.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Signature"] = signature
            headers["X-Timestamp"] = timestamp
            if key_id:
                headers["X-Key-Id"] = key_id

        return headers

    def _extract_approval_id(self, data: dict) -> Optional[str]:
        if not isinstance(data, dict):
            return None

        direct = data.get("approval_id") or data.get("id")
        if direct:
            return str(direct)

        nested = data.get("data")
        if isinstance(nested, dict):
            nested_id = nested.get("approval_id") or nested.get("id")
            if nested_id:
                return str(nested_id)

        return None

    def _map_fields(self, voucher: dict) -> dict:
        if not self.config.field_mapping:
            return voucher
        mapped = {}
        for src, dst in self.config.field_mapping.items():
            if src in voucher:
                mapped[dst] = voucher[src]
        return mapped

    @property
    def sync_mode(self) -> str:
        return "webhook" if self.config.use_webhook else "polling"
