"""
extensions/submission_gateway.py
统一外部提交通道抽象层（Submission Gateway）。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from agent_core.models import SubmitResult
from extensions.oa_connector import OAConnector

logger = logging.getLogger(__name__)


class SubmissionGateway(ABC):
    """外部系统提交网关抽象接口。"""

    @property
    @abstractmethod
    def channel(self) -> str:
        """通道标识，如 oa / accounting。"""

    @abstractmethod
    async def submit_voucher(self, voucher: dict) -> SubmitResult:
        """提交凭证，返回统一 SubmitResult。"""


@dataclass
class OASubmissionGateway(SubmissionGateway):
    """OA 通道适配器。"""

    connector: OAConnector

    @property
    def channel(self) -> str:
        return "oa"

    async def submit_voucher(self, voucher: dict) -> SubmitResult:
        return await self.connector.submit_voucher(voucher)


def create_submission_gateway(
    channel: str,
    oa_connector: Optional[OAConnector] = None,
) -> Optional[SubmissionGateway]:
    """按通道创建网关实例。当前已支持 OA。"""
    channel_norm = (channel or "").strip().lower()
    if channel_norm == "oa":
        if oa_connector is None:
            logger.warning("Submission channel 'oa' selected but OA connector is missing.")
            return None
        return OASubmissionGateway(oa_connector)

    logger.warning("Unsupported submission channel: %s", channel)
    return None
