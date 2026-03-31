"""
extensions/compliance_checker.py
合规检查模块 - 校验报销是否符合企业财务制度
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from agent_core.models import ComplianceResult, ComplianceViolation, VoucherDraft
from storage.voucher_repository import VoucherRepository


@dataclass
class ComplianceRules:
    """企业财务制度规则配置"""
    max_single_amount: Decimal = Decimal("50000")
    max_monthly_by_type: Decimal = Decimal("200000")
    ticket_validity_days: int = 180


class ComplianceChecker:
    """
    合规检查器。根据企业财务制度规则校验凭证合规性。
    检查规则：
    - 单笔报销金额上限
    - 同一费用类型月度累计上限（通过 VoucherRepository 查询）
    - 票据日期有效期
    """

    def __init__(
        self,
        voucher_repo: VoucherRepository,
        rules: ComplianceRules,
    ) -> None:
        self._repo = voucher_repo
        self._rules = rules

    async def check(
        self,
        voucher: VoucherDraft,
        expense_type: str = "",
        ticket_date: Optional[date] = None,
        check_date: Optional[date] = None,
    ) -> ComplianceResult:
        """
        校验凭证合规性。

        Args:
            voucher: 凭证草稿
            expense_type: 费用类型（用于月度累计查询）
            ticket_date: 票据开票日期（用于有效期校验）
            check_date: 校验基准日期，默认为今天
        """
        violations: list[ComplianceViolation] = []
        if check_date is None:
            check_date = date.today()

        # 规则1：单笔报销金额上限
        self._check_single_amount(voucher, violations)

        # 规则2：同一费用类型月度累计上限
        await self._check_monthly_cumulative(
            voucher, expense_type, check_date, violations
        )

        # 规则3：票据日期有效期
        self._check_ticket_validity(ticket_date, check_date, violations)

        return ComplianceResult(
            passed=len(violations) == 0,
            violations=violations,
        )

    def _check_single_amount(
        self,
        voucher: VoucherDraft,
        violations: list[ComplianceViolation],
    ) -> None:
        """检查单笔报销金额是否超过上限"""
        if voucher.total_debit > self._rules.max_single_amount:
            violations.append(ComplianceViolation(
                rule_name="单笔报销金额上限",
                description=(
                    f"单笔报销金额 {voucher.total_debit} 元超过上限 "
                    f"{self._rules.max_single_amount} 元"
                ),
                policy_reference="企业财务制度第X条：单笔报销金额不得超过"
                                 f" {self._rules.max_single_amount} 元",
            ))

    async def _check_monthly_cumulative(
        self,
        voucher: VoucherDraft,
        expense_type: str,
        check_date: date,
        violations: list[ComplianceViolation],
    ) -> None:
        """检查同一费用类型月度累计是否超过上限"""
        if not expense_type:
            return

        try:
            monthly_total = await self._repo.get_monthly_total(
                department=voucher.department,
                expense_type=expense_type,
                month=check_date,
            )
            projected = monthly_total + voucher.total_debit
            if projected > self._rules.max_monthly_by_type:
                violations.append(ComplianceViolation(
                    rule_name="月度累计上限",
                    description=(
                        f"部门 '{voucher.department}' 费用类型 '{expense_type}' "
                        f"本月累计 {monthly_total} 元，加上本笔 {voucher.total_debit} 元"
                        f"共计 {projected} 元，超过月度上限 "
                        f"{self._rules.max_monthly_by_type} 元"
                    ),
                    policy_reference="企业财务制度第Y条：同一费用类型月度累计报销"
                                     f"不得超过 {self._rules.max_monthly_by_type} 元",
                ))
        except Exception:
            # VoucherRepository 查询失败时跳过月度累计检查，不阻塞流程
            pass

    def _check_ticket_validity(
        self,
        ticket_date: Optional[date],
        check_date: date,
        violations: list[ComplianceViolation],
    ) -> None:
        """检查票据日期是否在有效期内"""
        if ticket_date is None:
            return

        delta = (check_date - ticket_date).days
        if delta > self._rules.ticket_validity_days:
            violations.append(ComplianceViolation(
                rule_name="票据日期有效期",
                description=(
                    f"票据开票日期 {ticket_date} 距报销日期 {check_date} "
                    f"已过 {delta} 天，超过有效期 "
                    f"{self._rules.ticket_validity_days} 天"
                ),
                policy_reference="企业财务制度第Z条：票据开票日期距报销日期"
                                 f"不得超过 {self._rules.ticket_validity_days} 天",
            ))
        elif delta < 0:
            violations.append(ComplianceViolation(
                rule_name="票据日期有效期",
                description=(
                    f"票据开票日期 {ticket_date} 晚于报销日期 {check_date}，"
                    "票据日期不合法"
                ),
                policy_reference="企业财务制度第Z条：票据开票日期不得晚于报销日期",
            ))
