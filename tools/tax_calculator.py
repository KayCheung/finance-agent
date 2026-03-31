"""
tools/tax_calculator.py
确定性价税分离计算工具 - 使用 Python Decimal 精确计算，避免浮点误差。

核心不变量：amount_without_tax + tax_amount == total_amount 恒成立。
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from agent_core.models import TaxResult


def calculate_tax(
    total_amount: Decimal, tax_rate: Decimal | None = None
) -> TaxResult:
    """
    确定性价税分离计算。

    Args:
        total_amount: 含税总额，必须为非负 Decimal。
        tax_rate: 税率（如 0.13 表示 13%），None 或 0 时视为免税。

    Returns:
        TaxResult，其中 amount_without_tax + tax_amount == total_amount 恒成立。

    Raises:
        ValueError: total_amount 为负数或非 Decimal 类型；tax_rate 为非 Decimal 类型。
    """
    # ── 参数校验 ──
    if not isinstance(total_amount, Decimal):
        raise ValueError(
            "total_amount must be of type Decimal, "
            f"got {type(total_amount).__name__}"
        )

    # Decimal('NaN') / Decimal('Inf') 等特殊值也视为无效
    if not total_amount.is_finite():
        raise ValueError(
            "total_amount must be a finite Decimal, "
            f"got {total_amount}"
        )

    if total_amount < 0:
        raise ValueError(
            "total_amount must be non-negative Decimal, "
            f"got {total_amount}"
        )

    if tax_rate is not None:
        if not isinstance(tax_rate, Decimal):
            raise ValueError(
                "tax_rate must be of type Decimal or None, "
                f"got {type(tax_rate).__name__}"
            )
        if not tax_rate.is_finite():
            raise ValueError(
                "tax_rate must be a finite Decimal, "
                f"got {tax_rate}"
            )
        if tax_rate < 0:
            raise ValueError(
                "tax_rate must be non-negative Decimal, "
                f"got {tax_rate}"
            )

    # ── 计算 ──
    if tax_rate is None or tax_rate == 0:
        # 免税：不含税价款 = 含税总额，税额 = 0
        amount_without_tax = total_amount
        tax_amount = Decimal("0")
    else:
        # 不含税价款 = 含税总额 / (1 + 税率)，ROUND_HALF_UP 到两位小数
        amount_without_tax = (total_amount / (1 + tax_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # 税额 = 含税总额 - 不含税价款（减法保证恒等式）
        tax_amount = total_amount - amount_without_tax

    balanced = amount_without_tax + tax_amount == total_amount

    return TaxResult(
        total_amount=total_amount,
        tax_rate=tax_rate if tax_rate is not None else Decimal("0"),
        amount_without_tax=amount_without_tax,
        tax_amount=tax_amount,
        balanced=balanced,
    )
