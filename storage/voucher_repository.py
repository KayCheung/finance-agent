"""
storage/voucher_repository.py
凭证数据仓库 - 独立于 SessionBackend，提供凭证查询检索能力
"""
import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from agent_core.models import ApprovalRecord, VoucherRecord

logger = logging.getLogger(__name__)


class VoucherQuery(BaseModel):
    """凭证多维度查询条件"""

    voucher_id: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    department: Optional[str] = None
    submitter: Optional[str] = None
    keyword: Optional[str] = None


class VoucherRepository:
    """
    凭证数据仓库，默认内存存储。
    当传入 storage_path 时自动启用 JSON 文件持久化。
    """

    def __init__(self, storage_path: str | None = None) -> None:
        self._vouchers: dict[str, VoucherRecord] = {}
        self._approvals: list[ApprovalRecord] = []
        self._storage_path: Path | None = Path(storage_path) if storage_path else None
        if self._storage_path:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    async def save(self, voucher: VoucherRecord) -> None:
        """保存或更新凭证记录"""
        self._vouchers[voucher.voucher_id] = voucher
        self._flush_to_disk()

    async def get_by_id(self, voucher_id: str) -> Optional[VoucherRecord]:
        """按凭证 ID 获取凭证"""
        return self._vouchers.get(voucher_id)

    async def query(self, q: VoucherQuery) -> list[VoucherRecord]:
        """多维度过滤查询凭证列表"""
        results: list[VoucherRecord] = []
        for voucher in self._vouchers.values():
            if not self._matches(voucher, q):
                continue
            results.append(voucher)
        return results

    async def search(self, keyword: str) -> list[VoucherRecord]:
        """按关键词搜索凭证摘要字段"""
        keyword_lower = keyword.lower()
        return [
            v
            for v in self._vouchers.values()
            if keyword_lower in v.summary.lower()
        ]

    async def get_monthly_total(self, department: str, expense_type: str, month: date) -> Decimal:
        """
        按部门 + 费用类型查询月度累计金额。
        month 参数取其年月部分，匹配该月内所有凭证。
        """
        total = Decimal("0")
        for voucher in self._vouchers.values():
            if voucher.department != department:
                continue
            if voucher.expense_type != expense_type:
                continue
            if voucher.created_at.year != month.year or voucher.created_at.month != month.month:
                continue
            total += voucher.total_amount
        return total

    async def get_similar_approvals(
        self,
        department: str,
        account_code: str,
        amount_range: tuple[Decimal, Decimal],
    ) -> list[ApprovalRecord]:
        """
        按部门、科目代码、金额区间查询历史审批记录。
        amount_range = (lower, upper)，由调用方根据凭证金额 ±30% 计算后传入。
        """
        lower, upper = amount_range
        return [
            a
            for a in self._approvals
            if a.department == department and a.account_code == account_code and lower <= a.amount <= upper
        ]

    async def add_approval(self, approval: ApprovalRecord) -> None:
        """添加审批记录（供测试和业务流程使用）"""
        self._approvals.append(approval)
        self._flush_to_disk()

    def _load_from_disk(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Failed to load voucher repository from %s: %s", self._storage_path, exc)
            return

        vouchers: dict[str, VoucherRecord] = {}
        for item in data.get("vouchers", []):
            try:
                voucher = VoucherRecord.model_validate(item)
                vouchers[voucher.voucher_id] = voucher
            except Exception as exc:
                logger.warning("Skipped invalid voucher record in repository: %s", exc)

        approvals: list[ApprovalRecord] = []
        for item in data.get("approvals", []):
            try:
                approvals.append(ApprovalRecord.model_validate(item))
            except Exception as exc:
                logger.warning("Skipped invalid approval record in repository: %s", exc)

        self._vouchers = vouchers
        self._approvals = approvals

    def _flush_to_disk(self) -> None:
        if not self._storage_path:
            return

        payload = {
            "vouchers": [v.model_dump(mode="json") for v in self._vouchers.values()],
            "approvals": [a.model_dump(mode="json") for a in self._approvals],
        }

        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to persist voucher repository to %s: %s", self._storage_path, exc)

    def _matches(self, voucher: VoucherRecord, q: VoucherQuery) -> bool:
        """检查凭证是否满足所有查询条件"""
        if q.voucher_id is not None and voucher.voucher_id != q.voucher_id:
            return False
        if q.date_from is not None and voucher.created_at.date() < q.date_from:
            return False
        if q.date_to is not None and voucher.created_at.date() > q.date_to:
            return False
        if q.department is not None and voucher.department != q.department:
            return False
        if q.submitter is not None and voucher.submitter != q.submitter:
            return False
        if q.keyword is not None and q.keyword.lower() not in voucher.summary.lower():
            return False
        return True
