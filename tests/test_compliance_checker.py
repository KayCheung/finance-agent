"""
tests/test_compliance_checker.py
ComplianceChecker 单元测试 + 属性测试
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from hypothesis import given, settings, strategies as st, assume

from agent_core.models import VoucherDraft, VoucherEntry, VoucherRecord
from extensions.compliance_checker import ComplianceChecker, ComplianceRules
from storage.voucher_repository import VoucherRepository


def _make_voucher_draft(
    amount: Decimal,
    department: str = "财务部",
    submitter: str = "张三",
) -> VoucherDraft:
    """Helper: create a minimal VoucherDraft."""
    return VoucherDraft(
        voucher_id="V-TEST-001",
        summary="测试凭证",
        department=department,
        submitter=submitter,
        usage="测试",
        entries=[
            VoucherEntry(
                account_code="6601",
                account_name="管理费用",
                debit=amount,
                credit=Decimal("0"),
            ),
            VoucherEntry(
                account_code="1001",
                account_name="库存现金",
                debit=Decimal("0"),
                credit=amount,
            ),
        ],
        total_debit=amount,
        total_credit=amount,
        balanced=True,
    )


# ── 单元测试 ──

@pytest.mark.asyncio
async def test_all_rules_pass():
    """所有规则通过时 passed=True"""
    repo = VoucherRepository()
    rules = ComplianceRules(
        max_single_amount=Decimal("100000"),
        max_monthly_by_type=Decimal("500000"),
        ticket_validity_days=180,
    )
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("5000"))
    result = await checker.check(
        voucher,
        expense_type="差旅费",
        ticket_date=date.today() - timedelta(days=10),
    )
    assert result.passed is True
    assert len(result.violations) == 0


@pytest.mark.asyncio
async def test_single_amount_exceeded():
    """单笔金额超限"""
    repo = VoucherRepository()
    rules = ComplianceRules(max_single_amount=Decimal("10000"))
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("15000"))
    result = await checker.check(voucher)
    assert result.passed is False
    assert any(v.rule_name == "单笔报销金额上限" for v in result.violations)


@pytest.mark.asyncio
async def test_monthly_cumulative_exceeded():
    """月度累计超限"""
    repo = VoucherRepository()
    # Pre-populate with existing vouchers
    now = datetime.now()
    await repo.save(VoucherRecord(
        voucher_id="V-EXIST-001",
        created_at=now,
        department="财务部",
        submitter="李四",
        summary="已有报销",
        usage="差旅",
        entries=[],
        total_amount=Decimal("180000"),
        expense_type="差旅费",
    ))
    rules = ComplianceRules(max_monthly_by_type=Decimal("200000"))
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("30000"))
    result = await checker.check(
        voucher,
        expense_type="差旅费",
        check_date=now.date(),
    )
    assert result.passed is False
    assert any(v.rule_name == "月度累计上限" for v in result.violations)


@pytest.mark.asyncio
async def test_ticket_date_expired():
    """票据日期超过有效期"""
    repo = VoucherRepository()
    rules = ComplianceRules(ticket_validity_days=180)
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("1000"))
    result = await checker.check(
        voucher,
        ticket_date=date.today() - timedelta(days=200),
    )
    assert result.passed is False
    assert any(v.rule_name == "票据日期有效期" for v in result.violations)


@pytest.mark.asyncio
async def test_ticket_date_future():
    """票据日期晚于报销日期"""
    repo = VoucherRepository()
    rules = ComplianceRules(ticket_validity_days=180)
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("1000"))
    result = await checker.check(
        voucher,
        ticket_date=date.today() + timedelta(days=5),
    )
    assert result.passed is False
    assert any("不合法" in v.description for v in result.violations)


@pytest.mark.asyncio
async def test_no_expense_type_skips_monthly():
    """未提供费用类型时跳过月度累计检查"""
    repo = VoucherRepository()
    rules = ComplianceRules(max_single_amount=Decimal("100000"))
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("5000"))
    result = await checker.check(voucher)
    assert result.passed is True


@pytest.mark.asyncio
async def test_multiple_violations():
    """多条规则同时违规"""
    repo = VoucherRepository()
    rules = ComplianceRules(
        max_single_amount=Decimal("10000"),
        ticket_validity_days=30,
    )
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(Decimal("20000"))
    result = await checker.check(
        voucher,
        ticket_date=date.today() - timedelta(days=60),
    )
    assert result.passed is False
    assert len(result.violations) >= 2


# ── Property 22: 合规检查规则覆盖 ──
# **Validates: Requirements 11.5, 11.6, 11.8**

@st.composite
def compliance_scenario(draw):
    """Generate random voucher amount, rules, and optional ticket date."""
    amount = draw(st.decimals(
        min_value=Decimal("1"),
        max_value=Decimal("500000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    max_single = draw(st.decimals(
        min_value=Decimal("1000"),
        max_value=Decimal("100000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    max_monthly = draw(st.decimals(
        min_value=Decimal("10000"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    validity_days = draw(st.integers(min_value=30, max_value=365))
    # ticket age in days (0 = today, could exceed validity)
    ticket_age_days = draw(st.integers(min_value=0, max_value=400))
    # existing monthly total for the same expense type
    existing_monthly = draw(st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("500000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    return {
        "amount": amount,
        "max_single": max_single,
        "max_monthly": max_monthly,
        "validity_days": validity_days,
        "ticket_age_days": ticket_age_days,
        "existing_monthly": existing_monthly,
    }


@given(scenario=compliance_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property22_compliance_rules_coverage(scenario):
    """
    Property 22: 合规检查规则覆盖
    生成随机凭证 + 随机规则配置，验证超限时 passed=False 且包含违规项。
    **Validates: Requirements 11.5, 11.6, 11.8**
    """
    amount = scenario["amount"]
    max_single = scenario["max_single"]
    max_monthly = scenario["max_monthly"]
    validity_days = scenario["validity_days"]
    ticket_age_days = scenario["ticket_age_days"]
    existing_monthly = scenario["existing_monthly"]

    repo = VoucherRepository()
    check_date = date.today()

    # Pre-populate existing monthly total
    if existing_monthly > 0:
        await repo.save(VoucherRecord(
            voucher_id="V-EXISTING",
            created_at=datetime.combine(check_date, datetime.min.time()),
            department="测试部",
            submitter="测试人",
            summary="已有报销",
            usage="测试",
            entries=[],
            total_amount=existing_monthly,
            expense_type="测试费用",
        ))

    rules = ComplianceRules(
        max_single_amount=max_single,
        max_monthly_by_type=max_monthly,
        ticket_validity_days=validity_days,
    )
    checker = ComplianceChecker(repo, rules)
    voucher = _make_voucher_draft(amount, department="测试部")
    ticket_date = check_date - timedelta(days=ticket_age_days)

    result = await checker.check(
        voucher,
        expense_type="测试费用",
        ticket_date=ticket_date,
        check_date=check_date,
    )

    # Determine expected violations
    expect_single_violation = amount > max_single
    expect_monthly_violation = (existing_monthly + amount) > max_monthly
    expect_ticket_violation = ticket_age_days > validity_days

    if expect_single_violation or expect_monthly_violation or expect_ticket_violation:
        assert result.passed is False
        assert len(result.violations) > 0

        # Each expected violation should have a corresponding entry
        violation_names = [v.rule_name for v in result.violations]

        if expect_single_violation:
            assert "单笔报销金额上限" in violation_names

        if expect_monthly_violation:
            assert "月度累计上限" in violation_names

        if expect_ticket_violation:
            assert "票据日期有效期" in violation_names

        # All violations must have policy_reference
        for v in result.violations:
            assert v.policy_reference != ""
            assert v.description != ""
    else:
        assert result.passed is True
        assert len(result.violations) == 0
