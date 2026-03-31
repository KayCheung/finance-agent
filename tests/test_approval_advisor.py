"""
tests/test_approval_advisor.py
ApprovalAdvisor 单元测试 + 属性测试
"""
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from hypothesis import given, settings, strategies as st

from agent_core.models import (
    ApprovalAdvice,
    ApprovalRecommendation,
    ApprovalRecord,
    ApprovalStatus,
    VoucherDraft,
    VoucherEntry,
)
from extensions.approval_advisor import ApprovalAdvisor
from storage.voucher_repository import VoucherRepository


def _make_voucher_draft(
    amount: Decimal,
    department: str = "财务部",
    account_code: str = "6601",
) -> VoucherDraft:
    """Helper: create a minimal VoucherDraft."""
    return VoucherDraft(
        voucher_id="V-TEST-001",
        summary="测试凭证",
        department=department,
        submitter="张三",
        usage="测试",
        entries=[
            VoucherEntry(
                account_code=account_code,
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


def _make_approval(
    department: str,
    account_code: str,
    amount: Decimal,
    status: ApprovalStatus,
) -> ApprovalRecord:
    return ApprovalRecord(
        voucher_id=f"V-HIST-{amount}",
        department=department,
        account_code=account_code,
        amount=amount,
        approval_status=status,
        created_at=datetime.now(),
    )


# ── 单元测试 ──

@pytest.mark.asyncio
async def test_no_similar_cases():
    """无历史相似案例时建议关注"""
    repo = VoucherRepository()
    advisor = ApprovalAdvisor(repo)
    voucher = _make_voucher_draft(Decimal("10000"))
    advice = await advisor.advise(voucher)
    assert advice.recommendation == ApprovalRecommendation.ATTENTION
    assert advice.similar_cases_count == 0
    assert advice.approval_rate == 0.0
    assert advice.reason != ""


@pytest.mark.asyncio
async def test_high_approval_rate():
    """高通过率时建议通过"""
    repo = VoucherRepository()
    # Add 10 approved records in range
    for i in range(10):
        await repo.add_approval(_make_approval(
            "财务部", "6601", Decimal("9000") + Decimal(str(i * 100)),
            ApprovalStatus.APPROVED,
        ))
    advisor = ApprovalAdvisor(repo)
    voucher = _make_voucher_draft(Decimal("10000"))
    advice = await advisor.advise(voucher)
    assert advice.recommendation == ApprovalRecommendation.APPROVE
    assert advice.similar_cases_count == 10
    assert advice.approval_rate >= 0.8


@pytest.mark.asyncio
async def test_low_approval_rate():
    """低通过率时建议驳回"""
    repo = VoucherRepository()
    # 8 rejected, 2 approved
    for i in range(8):
        await repo.add_approval(_make_approval(
            "财务部", "6601", Decimal("9500"),
            ApprovalStatus.REJECTED,
        ))
    for i in range(2):
        await repo.add_approval(_make_approval(
            "财务部", "6601", Decimal("10500"),
            ApprovalStatus.APPROVED,
        ))
    advisor = ApprovalAdvisor(repo)
    voucher = _make_voucher_draft(Decimal("10000"))
    advice = await advisor.advise(voucher)
    assert advice.recommendation == ApprovalRecommendation.REJECT
    assert advice.approval_rate < 0.5


@pytest.mark.asyncio
async def test_medium_approval_rate():
    """中等通过率时建议关注"""
    repo = VoucherRepository()
    # 6 approved, 4 rejected
    for i in range(6):
        await repo.add_approval(_make_approval(
            "财务部", "6601", Decimal("9500"),
            ApprovalStatus.APPROVED,
        ))
    for i in range(4):
        await repo.add_approval(_make_approval(
            "财务部", "6601", Decimal("10500"),
            ApprovalStatus.REJECTED,
        ))
    advisor = ApprovalAdvisor(repo)
    voucher = _make_voucher_draft(Decimal("10000"))
    advice = await advisor.advise(voucher)
    assert advice.recommendation == ApprovalRecommendation.ATTENTION
    assert 0.5 <= advice.approval_rate < 0.8


@pytest.mark.asyncio
async def test_amount_range_calculation():
    """验证金额区间为 ±30%"""
    repo = VoucherRepository()
    # Amount exactly at lower bound (10000 * 0.7 = 7000)
    await repo.add_approval(_make_approval(
        "财务部", "6601", Decimal("7000"), ApprovalStatus.APPROVED,
    ))
    # Amount exactly at upper bound (10000 * 1.3 = 13000)
    await repo.add_approval(_make_approval(
        "财务部", "6601", Decimal("13000"), ApprovalStatus.APPROVED,
    ))
    # Amount outside range
    await repo.add_approval(_make_approval(
        "财务部", "6601", Decimal("6999"), ApprovalStatus.APPROVED,
    ))
    advisor = ApprovalAdvisor(repo)
    voucher = _make_voucher_draft(Decimal("10000"))
    advice = await advisor.advise(voucher)
    # Should find 2 records (7000 and 13000), not 6999
    assert advice.similar_cases_count == 2


# ── Property 24: 审批建议完整性 ──
# **Validates: Requirements 11.9, 11.11**

@st.composite
def approval_scenario(draw):
    """Generate random historical approval data and a voucher."""
    amount = draw(st.decimals(
        min_value=Decimal("100"),
        max_value=Decimal("500000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    department = draw(st.sampled_from(["财务部", "研发部", "市场部"]))
    account_code = draw(st.sampled_from(["6601", "6602", "6603"]))

    # Generate 0-20 historical approval records
    num_records = draw(st.integers(min_value=0, max_value=20))
    records = []
    for _ in range(num_records):
        rec_amount = draw(st.decimals(
            min_value=Decimal("50"),
            max_value=Decimal("1000000"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ))
        rec_status = draw(st.sampled_from(list(ApprovalStatus)))
        rec_dept = draw(st.sampled_from(["财务部", "研发部", "市场部"]))
        rec_code = draw(st.sampled_from(["6601", "6602", "6603"]))
        records.append({
            "department": rec_dept,
            "account_code": rec_code,
            "amount": rec_amount,
            "status": rec_status,
        })

    return {
        "amount": amount,
        "department": department,
        "account_code": account_code,
        "records": records,
    }


@given(scenario=approval_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property24_approval_advice_completeness(scenario):
    """
    Property 24: 审批建议完整性
    生成随机历史数据和凭证，验证建议包含 recommendation、reason、
    similar_cases_count、approval_rate。
    **Validates: Requirements 11.9, 11.11**
    """
    repo = VoucherRepository()

    # Populate historical records
    for rec in scenario["records"]:
        await repo.add_approval(ApprovalRecord(
            voucher_id=f"V-HIST-{rec['amount']}",
            department=rec["department"],
            account_code=rec["account_code"],
            amount=rec["amount"],
            approval_status=rec["status"],
            created_at=datetime.now(),
        ))

    advisor = ApprovalAdvisor(repo)
    voucher = _make_voucher_draft(
        amount=scenario["amount"],
        department=scenario["department"],
        account_code=scenario["account_code"],
    )

    advice = await advisor.advise(voucher)

    # Verify completeness: all required fields present and valid
    assert isinstance(advice.recommendation, ApprovalRecommendation)
    assert advice.recommendation in [
        ApprovalRecommendation.APPROVE,
        ApprovalRecommendation.ATTENTION,
        ApprovalRecommendation.REJECT,
    ]
    assert isinstance(advice.reason, str) and len(advice.reason) > 0
    assert isinstance(advice.similar_cases_count, int) and advice.similar_cases_count >= 0
    assert isinstance(advice.approval_rate, float)
    assert 0.0 <= advice.approval_rate <= 1.0

    # If there are similar cases, approval_rate should be consistent
    if advice.similar_cases_count > 0:
        # Verify recommendation is consistent with approval_rate
        if advice.approval_rate >= 0.8:
            assert advice.recommendation == ApprovalRecommendation.APPROVE
        elif advice.approval_rate >= 0.5:
            assert advice.recommendation == ApprovalRecommendation.ATTENTION
        else:
            assert advice.recommendation == ApprovalRecommendation.REJECT
    else:
        # No similar cases → ATTENTION
        assert advice.recommendation == ApprovalRecommendation.ATTENTION
        assert advice.approval_rate == 0.0
