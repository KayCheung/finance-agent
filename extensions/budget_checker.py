"""
extensions/budget_checker.py
预算校验模块（可选）- 在生成凭证前检查部门预算余额
"""
from decimal import Decimal
from typing import Optional

from agent_core.models import BudgetResult


class BudgetChecker:
    """
    预算校验器。通过配置项控制是否启用，默认禁用。
    使用 dict 存储各部门预算余额，支持在测试中灵活填充。
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._budgets: dict[str, Decimal] = {}

    def set_budget(self, department: str, remaining: Decimal) -> None:
        """设置部门预算余额（供业务流程和测试使用）"""
        self._budgets[department] = remaining

    def get_budget(self, department: str) -> Optional[Decimal]:
        """查询部门预算余额"""
        return self._budgets.get(department)

    async def check(self, department: str, amount: Decimal) -> BudgetResult:
        """
        检查部门预算是否足够。
        - 未启用时直接返回 passed=True
        - 已启用时查询预算余额并与凭证金额比较
        - 超支时生成包含预算余额和超支金额的警告信息
        """
        if not self.enabled:
            return BudgetResult(
                enabled=False,
                passed=True,
                department=department,
                voucher_amount=amount,
            )

        budget_remaining = self._budgets.get(department)

        if budget_remaining is None:
            # 部门预算未配置，跳过检查不阻塞流程
            return BudgetResult(
                enabled=True,
                passed=True,
                department=department,
                voucher_amount=amount,
                warning_message=f"部门 '{department}' 预算数据未配置，跳过预算校验",
            )

        if amount > budget_remaining:
            overspend = amount - budget_remaining
            return BudgetResult(
                enabled=True,
                passed=False,
                department=department,
                budget_remaining=budget_remaining,
                voucher_amount=amount,
                overspend_amount=overspend,
                warning_message=(
                    f"预算超支警告：部门 '{department}' 当前预算余额为 {budget_remaining} 元，"
                    f"凭证金额 {amount} 元，超支 {overspend} 元"
                ),
            )

        return BudgetResult(
            enabled=True,
            passed=True,
            department=department,
            budget_remaining=budget_remaining,
            voucher_amount=amount,
        )
