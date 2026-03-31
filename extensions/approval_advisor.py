"""
extensions/approval_advisor.py
智能审批建议模块 - 基于历史数据和规则为审批人提供建议
"""
from decimal import Decimal

from agent_core.models import (
    ApprovalAdvice,
    ApprovalRecommendation,
    ApprovalStatus,
    VoucherDraft,
)
from storage.voucher_repository import VoucherRepository


class ApprovalAdvisor:
    """
    智能审批建议器。
    基于历史审批数据生成审批建议（建议通过、建议关注、建议驳回）。
    通过 VoucherRepository 查询历史相似凭证的审批记录。
    """

    AMOUNT_RANGE_RATIO: float = 0.3  # 金额区间浮动比例，±30%

    def __init__(self, voucher_repo: VoucherRepository) -> None:
        self._repo = voucher_repo

    async def advise(self, voucher: VoucherDraft) -> ApprovalAdvice:
        """
        为凭证生成审批建议。

        1. 根据凭证金额计算相似区间：(amount * 0.7, amount * 1.3)
        2. 通过 VoucherRepository.get_similar_approvals 查询历史相似凭证
        3. 统计通过率，生成建议 + 依据
        """
        amount = voucher.total_debit
        lower = max(Decimal("0"), amount * Decimal(str(1 - self.AMOUNT_RANGE_RATIO)))
        upper = amount * Decimal(str(1 + self.AMOUNT_RANGE_RATIO))

        # 取第一个分录的科目代码作为匹配条件
        account_code = voucher.entries[0].account_code if voucher.entries else ""

        similar = await self._repo.get_similar_approvals(
            department=voucher.department,
            account_code=account_code,
            amount_range=(lower, upper),
        )

        similar_count = len(similar)

        if similar_count == 0:
            return ApprovalAdvice(
                recommendation=ApprovalRecommendation.ATTENTION,
                reason="无历史相似案例可参考，建议人工审核关注",
                similar_cases_count=0,
                approval_rate=0.0,
            )

        approved_count = sum(
            1 for a in similar if a.approval_status == ApprovalStatus.APPROVED
        )
        approval_rate = approved_count / similar_count

        recommendation = self._determine_recommendation(approval_rate)
        reason = self._build_reason(similar_count, approval_rate, recommendation)

        return ApprovalAdvice(
            recommendation=recommendation,
            reason=reason,
            similar_cases_count=similar_count,
            approval_rate=round(approval_rate, 4),
        )

    @staticmethod
    def _determine_recommendation(
        approval_rate: float,
    ) -> ApprovalRecommendation:
        """根据通过率确定建议"""
        if approval_rate >= 0.8:
            return ApprovalRecommendation.APPROVE
        elif approval_rate >= 0.5:
            return ApprovalRecommendation.ATTENTION
        else:
            return ApprovalRecommendation.REJECT

    @staticmethod
    def _build_reason(
        similar_count: int,
        approval_rate: float,
        recommendation: ApprovalRecommendation,
    ) -> str:
        """构建判断依据说明"""
        rate_pct = f"{approval_rate:.0%}"
        base = f"参考 {similar_count} 个历史相似案例，通过率 {rate_pct}"
        if recommendation == ApprovalRecommendation.APPROVE:
            return f"{base}，历史通过率较高，建议通过"
        elif recommendation == ApprovalRecommendation.ATTENTION:
            return f"{base}，通过率一般，建议关注审核"
        else:
            return f"{base}，历史通过率较低，建议驳回"
