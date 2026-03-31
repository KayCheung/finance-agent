"""
tests/test_budget_checker.py
BudgetChecker 单元测试 + 属性测试
"""
from decimal import Decimal

import pytest
import pytest_asyncio
from hypothesis import given, settings, strategies as st

from extensions.budget_checker import BudgetChecker


# ── 单元测试 ──

@pytest.mark.asyncio
async def test_disabled_returns_passed():
    """未启用时直接返回 passed=True（需求 11.4）"""
    checker = BudgetChecker(enabled=False)
    result = await checker.check("财务部", Decimal("10000"))
    assert result.enabled is False
    assert result.passed is True


@pytest.mark.asyncio
async def test_enabled_within_budget():
    """已启用且金额在预算内，返回 passed=True"""
    checker = BudgetChecker(enabled=True)
    checker.set_budget("财务部", Decimal("50000"))
    result = await checker.check("财务部", Decimal("30000"))
    assert result.enabled is True
    assert result.passed is True
    assert result.budget_remaining == Decimal("50000")
    assert result.overspend_amount is None


@pytest.mark.asyncio
async def test_enabled_exact_budget():
    """金额恰好等于预算余额，应通过"""
    checker = BudgetChecker(enabled=True)
    checker.set_budget("研发部", Decimal("10000"))
    result = await checker.check("研发部", Decimal("10000"))
    assert result.passed is True


@pytest.mark.asyncio
async def test_enabled_overspend():
    """金额超过预算余额，返回 passed=False + 警告"""
    checker = BudgetChecker(enabled=True)
    checker.set_budget("市场部", Decimal("20000"))
    result = await checker.check("市场部", Decimal("25000"))
    assert result.passed is False
    assert result.overspend_amount == Decimal("5000")
    assert result.budget_remaining == Decimal("20000")
    assert result.warning_message is not None
    assert "20000" in result.warning_message
    assert "5000" in result.warning_message


@pytest.mark.asyncio
async def test_enabled_department_not_configured():
    """部门预算未配置时跳过检查"""
    checker = BudgetChecker(enabled=True)
    result = await checker.check("未知部门", Decimal("1000"))
    assert result.passed is True
    assert result.warning_message is not None


# ── Property 23: 预算超支警告 ──
# **Validates: Requirements 11.2, 11.3**

@given(
    budget=st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=2, allow_nan=False, allow_infinity=False),
    amount=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("2000000"), places=2, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property23_budget_overspend_warning(budget, amount):
    """
    Property 23: 预算超支警告
    生成随机预算余额和凭证金额，验证超支时包含预算余额和超支金额的警告。
    **Validates: Requirements 11.2, 11.3**
    """
    checker = BudgetChecker(enabled=True)
    checker.set_budget("测试部门", budget)
    result = await checker.check("测试部门", amount)

    assert result.enabled is True
    assert result.voucher_amount == amount
    assert result.budget_remaining == budget

    if amount > budget:
        # 超支场景
        assert result.passed is False
        expected_overspend = amount - budget
        assert result.overspend_amount == expected_overspend
        assert result.warning_message is not None
        # 警告信息应包含预算余额和超支金额
        assert str(budget) in result.warning_message
        assert str(expected_overspend) in result.warning_message
    else:
        # 预算充足
        assert result.passed is True
        assert result.overspend_amount is None
