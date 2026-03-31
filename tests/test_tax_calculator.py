"""
tests/test_tax_calculator.py
Tax_Calculator 的属性测试和单元测试

Feature: finance-agent-architecture-upgrade
"""
from decimal import Decimal

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent_core.models import TaxResult
from tools.tax_calculator import calculate_tax


# ── Hypothesis 自定义策略 ──

# 生成有效的含税总额（正数 Decimal，两位小数）
amount_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1e8"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# 生成有效的税率（常见增值税税率）
tax_rate_strategy = st.sampled_from([
    Decimal("0"),
    Decimal("0.01"),
    Decimal("0.03"),
    Decimal("0.06"),
    Decimal("0.09"),
    Decimal("0.13"),
])


# ── Property 1: 价税分离恒等式不变量 ──
# Feature: finance-agent-architecture-upgrade, Property 1: 价税分离恒等式不变量


class TestProperty1TaxIdentityInvariant:
    """
    Property 1: 价税分离恒等式不变量

    For any 有效的含税总额（正数）和税率（≥0），Tax_Calculator 计算的
    amount_without_tax + tax_amount 必须严格等于 total_amount，
    且 amount_without_tax 等于 total_amount / (1 + tax_rate) 四舍五入到小数点后两位。

    **Validates: Requirements 1.1, 1.2, 1.3**
    """

    @given(total_amount=amount_strategy, tax_rate=tax_rate_strategy)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_identity_invariant(self, total_amount: Decimal, tax_rate: Decimal):
        """
        验证 amount_without_tax + tax_amount == total_amount 恒成立。

        **Validates: Requirements 1.1, 1.2, 1.3**
        """
        result = calculate_tax(total_amount, tax_rate)

        # 恒等式：不含税价款 + 税额 == 含税总额
        assert result.amount_without_tax + result.tax_amount == result.total_amount, (
            f"Identity violated: {result.amount_without_tax} + {result.tax_amount} "
            f"!= {result.total_amount}"
        )

        # balanced 标志必须为 True
        assert result.balanced is True, (
            f"balanced should be True but got False for total={total_amount}, rate={tax_rate}"
        )

        # total_amount 应原样保留
        assert result.total_amount == total_amount

        # tax_rate 应正确记录
        assert result.tax_rate == tax_rate

    @given(total_amount=amount_strategy, tax_rate=tax_rate_strategy)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_amount_without_tax_formula(self, total_amount: Decimal, tax_rate: Decimal):
        """
        验证 amount_without_tax == total_amount / (1 + tax_rate) 四舍五入到两位小数。

        **Validates: Requirements 1.1**
        """
        from decimal import ROUND_HALF_UP

        result = calculate_tax(total_amount, tax_rate)

        if tax_rate == Decimal("0"):
            # 税率为 0 时，不含税价款 = 含税总额
            assert result.amount_without_tax == total_amount
            assert result.tax_amount == Decimal("0")
        else:
            # 验证公式：不含税价款 = 含税总额 / (1 + 税率)，ROUND_HALF_UP
            expected = (total_amount / (1 + tax_rate)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            assert result.amount_without_tax == expected, (
                f"Formula mismatch: expected {expected}, got {result.amount_without_tax} "
                f"for total={total_amount}, rate={tax_rate}"
            )


# ── Property 2: 无效输入错误处理 ──
# Feature: finance-agent-architecture-upgrade, Property 2: 无效输入错误处理


class TestProperty2InvalidInputErrorHandling:
    """
    Property 2: 无效输入错误处理

    For any 负数或非数值类型的含税总额输入，Tax_Calculator 必须抛出包含参数名称和
    期望类型的错误信息，而非返回计算结果。

    **Validates: Requirements 1.5**
    """

    @given(
        invalid_amount=st.one_of(
            st.integers(max_value=-1),
            st.text(),
            st.none(),
        )
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_invalid_total_amount_raises_value_error(self, invalid_amount):
        """
        验证非 Decimal 类型或负数的 total_amount 输入抛出 ValueError，
        且错误信息包含参数名称 'total_amount' 和期望类型信息。

        **Validates: Requirements 1.5**
        """
        with pytest.raises(ValueError) as exc_info:
            calculate_tax(invalid_amount)

        error_msg = str(exc_info.value)
        # 错误信息必须包含参数名称
        assert "total_amount" in error_msg, (
            f"Error message should contain 'total_amount', got: {error_msg}"
        )
        # 错误信息必须包含类型相关信息（Decimal 或 type 名称）
        assert "Decimal" in error_msg or type(invalid_amount).__name__ in error_msg, (
            f"Error message should contain type info, got: {error_msg}"
        )

    @given(
        invalid_rate=st.one_of(
            st.integers(),
            st.text(),
        )
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_invalid_tax_rate_raises_value_error(self, invalid_rate):
        """
        验证非 Decimal 类型的 tax_rate 输入抛出 ValueError，
        且错误信息包含参数名称 'tax_rate' 和期望类型信息。

        **Validates: Requirements 1.5**
        """
        valid_amount = Decimal("100.00")
        with pytest.raises(ValueError) as exc_info:
            calculate_tax(valid_amount, invalid_rate)

        error_msg = str(exc_info.value)
        # 错误信息必须包含参数名称
        assert "tax_rate" in error_msg, (
            f"Error message should contain 'tax_rate', got: {error_msg}"
        )
        # 错误信息必须包含类型相关信息
        assert "Decimal" in error_msg or type(invalid_rate).__name__ in error_msg, (
            f"Error message should contain type info, got: {error_msg}"
        )

    @given(
        negative_amount=st.decimals(
            max_value=Decimal("-0.01"),
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_negative_decimal_amount_raises_value_error(self, negative_amount):
        """
        验证负数 Decimal 的 total_amount 输入抛出 ValueError，
        且错误信息包含参数名称。

        **Validates: Requirements 1.5**
        """
        with pytest.raises(ValueError) as exc_info:
            calculate_tax(negative_amount)

        error_msg = str(exc_info.value)
        assert "total_amount" in error_msg, (
            f"Error message should contain 'total_amount', got: {error_msg}"
        )


# ── 单元测试：Tax_Calculator 典型场景 ──
# Feature: finance-agent-architecture-upgrade, Task 4.4


class TestTaxCalculatorTypicalScenarios:
    """
    Tax_Calculator 典型场景单元测试。
    使用具体已知值验证各税率下的计算结果。

    **Validates: Requirements 1.1, 1.4**
    """

    # ── 税率 13% ──

    def test_rate_13_percent_total_100(self):
        """含税100元，税率13%：不含税88.50，税额11.50"""
        result = calculate_tax(Decimal("100"), Decimal("0.13"))
        assert result.amount_without_tax == Decimal("88.50")
        assert result.tax_amount == Decimal("11.50")
        assert result.total_amount == Decimal("100")
        assert result.tax_rate == Decimal("0.13")
        assert result.balanced is True

    def test_rate_13_percent_total_1130(self):
        """含税1130元，税率13%：不含税1000.00，税额130.00"""
        result = calculate_tax(Decimal("1130"), Decimal("0.13"))
        assert result.amount_without_tax == Decimal("1000.00")
        assert result.tax_amount == Decimal("130.00")
        assert result.balanced is True

    # ── 税率 9% ──

    def test_rate_9_percent_total_109(self):
        """含税109元，税率9%：不含税100.00，税额9.00"""
        result = calculate_tax(Decimal("109"), Decimal("0.09"))
        assert result.amount_without_tax == Decimal("100.00")
        assert result.tax_amount == Decimal("9.00")
        assert result.balanced is True

    def test_rate_9_percent_total_500(self):
        """含税500元，税率9%：不含税458.72，税额41.28"""
        result = calculate_tax(Decimal("500"), Decimal("0.09"))
        assert result.amount_without_tax == Decimal("458.72")
        assert result.tax_amount == Decimal("41.28")
        assert result.balanced is True

    # ── 税率 6% ──

    def test_rate_6_percent_total_1000(self):
        """含税1000元，税率6%：不含税943.40，税额56.60"""
        result = calculate_tax(Decimal("1000"), Decimal("0.06"))
        assert result.amount_without_tax == Decimal("943.40")
        assert result.tax_amount == Decimal("56.60")
        assert result.balanced is True

    def test_rate_6_percent_total_106(self):
        """含税106元，税率6%：不含税100.00，税额6.00"""
        result = calculate_tax(Decimal("106"), Decimal("0.06"))
        assert result.amount_without_tax == Decimal("100.00")
        assert result.tax_amount == Decimal("6.00")
        assert result.balanced is True

    # ── 税率 3% ──

    def test_rate_3_percent_total_103(self):
        """含税103元，税率3%：不含税100.00，税额3.00"""
        result = calculate_tax(Decimal("103"), Decimal("0.03"))
        assert result.amount_without_tax == Decimal("100.00")
        assert result.tax_amount == Decimal("3.00")
        assert result.balanced is True

    def test_rate_3_percent_total_250(self):
        """含税250元，税率3%：不含税242.72，税额7.28"""
        result = calculate_tax(Decimal("250"), Decimal("0.03"))
        assert result.amount_without_tax == Decimal("242.72")
        assert result.tax_amount == Decimal("7.28")
        assert result.balanced is True

    # ── 税率 0% ──

    def test_rate_zero_total_200(self):
        """含税200元，税率0%：不含税200.00，税额0"""
        result = calculate_tax(Decimal("200"), Decimal("0"))
        assert result.amount_without_tax == Decimal("200")
        assert result.tax_amount == Decimal("0")
        assert result.tax_rate == Decimal("0")
        assert result.balanced is True

    def test_rate_zero_total_9999(self):
        """含税9999元，税率0%：不含税9999，税额0"""
        result = calculate_tax(Decimal("9999"), Decimal("0"))
        assert result.amount_without_tax == Decimal("9999")
        assert result.tax_amount == Decimal("0")
        assert result.balanced is True

    # ── 税率 None（未提供） ──

    def test_rate_none_total_500(self):
        """含税500元，未提供税率：不含税500，税额0"""
        result = calculate_tax(Decimal("500"), None)
        assert result.amount_without_tax == Decimal("500")
        assert result.tax_amount == Decimal("0")
        assert result.tax_rate == Decimal("0")
        assert result.balanced is True

    def test_rate_none_total_0_01(self):
        """含税0.01元，未提供税率：不含税0.01，税额0"""
        result = calculate_tax(Decimal("0.01"), None)
        assert result.amount_without_tax == Decimal("0.01")
        assert result.tax_amount == Decimal("0")
        assert result.balanced is True

    # ── 小金额边界 ──

    def test_small_amount_with_rate_13(self):
        """含税0.01元，税率13%：不含税0.01，税额0.00"""
        result = calculate_tax(Decimal("0.01"), Decimal("0.13"))
        assert result.amount_without_tax == Decimal("0.01")
        assert result.tax_amount == Decimal("0.00")
        assert result.balanced is True

    # ── 默认参数（不传 tax_rate） ──

    def test_default_rate_omitted(self):
        """不传 tax_rate 参数，默认为 None，等同免税"""
        result = calculate_tax(Decimal("300"))
        assert result.amount_without_tax == Decimal("300")
        assert result.tax_amount == Decimal("0")
        assert result.tax_rate == Decimal("0")
        assert result.balanced is True
