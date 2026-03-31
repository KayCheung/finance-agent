"""
tests/test_voucher_repository.py
VoucherRepository 单元测试
"""
import pytest
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
import uuid

from agent_core.models import (
    ApprovalRecord,
    ApprovalStatus,
    VoucherEntry,
    VoucherRecord,
)
from storage.voucher_repository import VoucherQuery, VoucherRepository


def _make_voucher(
    voucher_id: str = "VOU-001",
    department: str = "财务部",
    submitter: str = "张三",
    summary: str = "差旅报销",
    expense_type: str = "差旅费",
    total_amount: Decimal = Decimal("1000"),
    created_at: datetime | None = None,
) -> VoucherRecord:
    return VoucherRecord(
        voucher_id=voucher_id,
        created_at=created_at or datetime(2024, 6, 15, 10, 0, 0),
        department=department,
        submitter=submitter,
        summary=summary,
        usage="出差",
        entries=[VoucherEntry(account_code="6601", account_name="差旅费", debit=total_amount)],
        total_amount=total_amount,
        expense_type=expense_type,
    )


@pytest.fixture
def repo() -> VoucherRepository:
    return VoucherRepository()


# ── save / get_by_id ──

@pytest.mark.asyncio
async def test_save_and_get_by_id(repo: VoucherRepository):
    v = _make_voucher()
    await repo.save(v)
    result = await repo.get_by_id("VOU-001")
    assert result is not None
    assert result.voucher_id == "VOU-001"
    assert result.total_amount == Decimal("1000")


@pytest.mark.asyncio
async def test_get_by_id_not_found(repo: VoucherRepository):
    result = await repo.get_by_id("nonexistent")
    assert result is None


# ── query (multi-dimension filtering) ──

@pytest.mark.asyncio
async def test_query_by_department(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", department="财务部"))
    await repo.save(_make_voucher(voucher_id="V2", department="技术部"))
    results = await repo.query(VoucherQuery(department="财务部"))
    assert len(results) == 1
    assert results[0].voucher_id == "V1"


@pytest.mark.asyncio
async def test_query_by_date_range(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", created_at=datetime(2024, 1, 10)))
    await repo.save(_make_voucher(voucher_id="V2", created_at=datetime(2024, 6, 15)))
    await repo.save(_make_voucher(voucher_id="V3", created_at=datetime(2024, 12, 1)))
    results = await repo.query(VoucherQuery(date_from=date(2024, 3, 1), date_to=date(2024, 9, 30)))
    assert len(results) == 1
    assert results[0].voucher_id == "V2"


@pytest.mark.asyncio
async def test_query_by_submitter(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", submitter="张三"))
    await repo.save(_make_voucher(voucher_id="V2", submitter="李四"))
    results = await repo.query(VoucherQuery(submitter="李四"))
    assert len(results) == 1
    assert results[0].voucher_id == "V2"


@pytest.mark.asyncio
async def test_query_by_keyword(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", summary="差旅报销-北京出差"))
    await repo.save(_make_voucher(voucher_id="V2", summary="办公用品采购"))
    results = await repo.query(VoucherQuery(keyword="北京"))
    assert len(results) == 1
    assert results[0].voucher_id == "V1"


@pytest.mark.asyncio
async def test_query_combined_filters(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", department="财务部", submitter="张三"))
    await repo.save(_make_voucher(voucher_id="V2", department="财务部", submitter="李四"))
    await repo.save(_make_voucher(voucher_id="V3", department="技术部", submitter="张三"))
    results = await repo.query(VoucherQuery(department="财务部", submitter="张三"))
    assert len(results) == 1
    assert results[0].voucher_id == "V1"


@pytest.mark.asyncio
async def test_query_empty_returns_all(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1"))
    await repo.save(_make_voucher(voucher_id="V2"))
    results = await repo.query(VoucherQuery())
    assert len(results) == 2


# ── search ──

@pytest.mark.asyncio
async def test_search_keyword_in_summary(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", summary="北京差旅报销"))
    await repo.save(_make_voucher(voucher_id="V2", summary="上海办公用品"))
    results = await repo.search("差旅")
    assert len(results) == 1
    assert results[0].voucher_id == "V1"


@pytest.mark.asyncio
async def test_search_case_insensitive(repo: VoucherRepository):
    await repo.save(_make_voucher(voucher_id="V1", summary="Office Supplies"))
    results = await repo.search("office")
    assert len(results) == 1


# ── get_monthly_total ──

@pytest.mark.asyncio
async def test_get_monthly_total(repo: VoucherRepository):
    await repo.save(_make_voucher(
        voucher_id="V1", department="财务部", expense_type="差旅费",
        total_amount=Decimal("1000"), created_at=datetime(2024, 6, 10),
    ))
    await repo.save(_make_voucher(
        voucher_id="V2", department="财务部", expense_type="差旅费",
        total_amount=Decimal("2000"), created_at=datetime(2024, 6, 20),
    ))
    await repo.save(_make_voucher(
        voucher_id="V3", department="财务部", expense_type="差旅费",
        total_amount=Decimal("500"), created_at=datetime(2024, 7, 5),
    ))
    total = await repo.get_monthly_total("财务部", "差旅费", date(2024, 6, 1))
    assert total == Decimal("3000")


@pytest.mark.asyncio
async def test_get_monthly_total_different_department(repo: VoucherRepository):
    await repo.save(_make_voucher(
        voucher_id="V1", department="财务部", expense_type="差旅费",
        total_amount=Decimal("1000"), created_at=datetime(2024, 6, 10),
    ))
    await repo.save(_make_voucher(
        voucher_id="V2", department="技术部", expense_type="差旅费",
        total_amount=Decimal("2000"), created_at=datetime(2024, 6, 10),
    ))
    total = await repo.get_monthly_total("财务部", "差旅费", date(2024, 6, 1))
    assert total == Decimal("1000")


@pytest.mark.asyncio
async def test_get_monthly_total_no_match(repo: VoucherRepository):
    await repo.save(_make_voucher(
        voucher_id="V1", department="财务部", expense_type="差旅费",
        total_amount=Decimal("1000"), created_at=datetime(2024, 6, 10),
    ))
    total = await repo.get_monthly_total("财务部", "办公费", date(2024, 6, 1))
    assert total == Decimal("0")


# ── get_similar_approvals ──

@pytest.mark.asyncio
async def test_get_similar_approvals(repo: VoucherRepository):
    await repo.add_approval(ApprovalRecord(
        voucher_id="V1", department="财务部", account_code="6601",
        amount=Decimal("800"), approval_status=ApprovalStatus.APPROVED,
        created_at=datetime(2024, 5, 1),
    ))
    await repo.add_approval(ApprovalRecord(
        voucher_id="V2", department="财务部", account_code="6601",
        amount=Decimal("5000"), approval_status=ApprovalStatus.REJECTED,
        created_at=datetime(2024, 5, 10),
    ))
    await repo.add_approval(ApprovalRecord(
        voucher_id="V3", department="技术部", account_code="6601",
        amount=Decimal("900"), approval_status=ApprovalStatus.APPROVED,
        created_at=datetime(2024, 5, 15),
    ))
    # amount=1000, ±30% → (700, 1300)
    results = await repo.get_similar_approvals(
        "财务部", "6601", (Decimal("700"), Decimal("1300"))
    )
    assert len(results) == 1
    assert results[0].voucher_id == "V1"


@pytest.mark.asyncio
async def test_get_similar_approvals_no_match(repo: VoucherRepository):
    await repo.add_approval(ApprovalRecord(
        voucher_id="V1", department="财务部", account_code="6601",
        amount=Decimal("100"), approval_status=ApprovalStatus.APPROVED,
        created_at=datetime(2024, 5, 1),
    ))
    results = await repo.get_similar_approvals(
        "财务部", "6601", (Decimal("700"), Decimal("1300"))
    )
    assert len(results) == 0


# ── Hypothesis 策略与属性测试 ──

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ── 自定义 VoucherRecord 生成策略 ──

_voucher_id_st = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=4,
    max_size=24,
).map(lambda s: f"VOU-{s}")

_department_st = st.sampled_from(["财务部", "技术部", "市场部", "人事部", "销售部"])
_submitter_st = st.sampled_from(["张三", "李四", "王五", "赵六", "钱七"])
_summary_st = st.text(min_size=1, max_size=60).filter(lambda s: s.strip() != "")
_expense_type_st = st.sampled_from(["差旅费", "交通费", "办公费", "招待费", "通讯费"])

_amount_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_datetime_st = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)

_voucher_entry_st = st.builds(
    VoucherEntry,
    account_code=st.just("6601"),
    account_name=st.just("差旅费"),
    debit=_amount_st,
    credit=st.just(Decimal("0")),
)

_voucher_record_st = st.builds(
    VoucherRecord,
    voucher_id=_voucher_id_st,
    created_at=_datetime_st,
    department=_department_st,
    submitter=_submitter_st,
    summary=_summary_st,
    usage=st.just("报销"),
    entries=st.lists(_voucher_entry_st, min_size=1, max_size=3),
    total_amount=_amount_st,
    expense_type=_expense_type_st,
)


# ── Property 18: 凭证存储往返一致性 ──
# Feature: finance-agent-architecture-upgrade, Property 18: 凭证存储往返一致性
# **Validates: Requirements 8.1**


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(voucher=_voucher_record_st)
async def test_property18_voucher_save_get_roundtrip(voucher: VoucherRecord):
    """
    Property 18: 凭证存储往返一致性
    For any valid VoucherRecord, save → get_by_id should return equivalent data.
    """
    repo = VoucherRepository()
    await repo.save(voucher)
    loaded = await repo.get_by_id(voucher.voucher_id)

    assert loaded is not None
    assert loaded.voucher_id == voucher.voucher_id
    assert loaded.created_at == voucher.created_at
    assert loaded.department == voucher.department
    assert loaded.submitter == voucher.submitter
    assert loaded.summary == voucher.summary
    assert loaded.usage == voucher.usage
    assert loaded.entries == voucher.entries
    assert loaded.total_amount == voucher.total_amount
    assert loaded.approval_status == voucher.approval_status
    assert loaded.expense_type == voucher.expense_type
    assert loaded == voucher


# ── Property 19: 凭证查询过滤正确性 ──
# Feature: finance-agent-architecture-upgrade, Property 19: 凭证查询过滤正确性
# **Validates: Requirements 8.2, 8.6**


_optional_department_st = st.one_of(st.none(), _department_st)
_optional_submitter_st = st.one_of(st.none(), _submitter_st)
_optional_date_st = st.one_of(
    st.none(),
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
)
_optional_keyword_st = st.one_of(
    st.none(),
    st.sampled_from(["差旅", "办公", "报销", "采购", "出差"]),
)


@st.composite
def _voucher_query_st(draw):
    """Generate a VoucherQuery with random filter conditions."""
    date_from = draw(_optional_date_st)
    date_to = draw(_optional_date_st)
    # Ensure date_from <= date_to when both are set
    if date_from is not None and date_to is not None and date_from > date_to:
        date_from, date_to = date_to, date_from
    return VoucherQuery(
        department=draw(_optional_department_st),
        submitter=draw(_optional_submitter_st),
        date_from=date_from,
        date_to=date_to,
        keyword=draw(_optional_keyword_st),
    )


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    vouchers=st.lists(_voucher_record_st, min_size=1, max_size=10, unique_by=lambda v: v.voucher_id),
    query=_voucher_query_st(),
)
async def test_property19_query_filter_correctness(
    vouchers: list[VoucherRecord],
    query: VoucherQuery,
):
    """
    Property 19: 凭证查询过滤正确性
    For any set of vouchers and any query conditions, all returned results
    must satisfy every specified filter.
    """
    repo = VoucherRepository()
    for v in vouchers:
        await repo.save(v)

    results = await repo.query(query)

    for r in results:
        if query.department is not None:
            assert r.department == query.department
        if query.submitter is not None:
            assert r.submitter == query.submitter
        if query.date_from is not None:
            assert r.created_at.date() >= query.date_from
        if query.date_to is not None:
            assert r.created_at.date() <= query.date_to
        if query.keyword is not None:
            assert query.keyword.lower() in r.summary.lower()

    # Also verify completeness: every voucher that matches should be in results
    result_ids = {r.voucher_id for r in results}
    for v in vouchers:
        matches = True
        if query.department is not None and v.department != query.department:
            matches = False
        if query.submitter is not None and v.submitter != query.submitter:
            matches = False
        if query.date_from is not None and v.created_at.date() < query.date_from:
            matches = False
        if query.date_to is not None and v.created_at.date() > query.date_to:
            matches = False
        if query.keyword is not None and query.keyword.lower() not in v.summary.lower():
            matches = False
        if matches:
            assert v.voucher_id in result_ids


# ── Property 20: 月度累计金额聚合正确性 ──
# Feature: finance-agent-architecture-upgrade, Property 20: 月度累计金额聚合正确性
# **Validates: Requirements 8.7**


@st.composite
def _monthly_total_scenario(draw):
    """
    Generate a set of vouchers and a specific (department, expense_type, month)
    query for get_monthly_total verification.
    """
    target_dept = draw(_department_st)
    target_expense = draw(_expense_type_st)
    target_year = draw(st.integers(min_value=2020, max_value=2030))
    target_month = draw(st.integers(min_value=1, max_value=12))

    vouchers = draw(st.lists(_voucher_record_st, min_size=1, max_size=10, unique_by=lambda v: v.voucher_id))
    query_date = date(target_year, target_month, 1)

    return vouchers, target_dept, target_expense, query_date


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(scenario=_monthly_total_scenario())
async def test_property20_monthly_total_aggregation(scenario):
    """
    Property 20: 月度累计金额聚合正确性
    For any department, expense_type, and month, get_monthly_total must equal
    the manual sum of total_amount for matching vouchers.
    """
    vouchers, target_dept, target_expense, query_date = scenario

    repo = VoucherRepository()
    for v in vouchers:
        await repo.save(v)

    result = await repo.get_monthly_total(target_dept, target_expense, query_date)

    # Manual calculation
    expected = Decimal("0")
    for v in vouchers:
        if (v.department == target_dept
                and v.expense_type == target_expense
                and v.created_at.year == query_date.year
                and v.created_at.month == query_date.month):
            expected += v.total_amount

    assert result == expected


@pytest.mark.asyncio
async def test_persistent_repo_save_and_reload():
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    storage_file = temp_dir / f"vouchers-{uuid.uuid4().hex}.json"
    v = _make_voucher(voucher_id="V-PERSIST-1")

    repo = VoucherRepository(storage_path=str(storage_file))
    await repo.save(v)

    reloaded = VoucherRepository(storage_path=str(storage_file))
    loaded = await reloaded.get_by_id("V-PERSIST-1")

    assert loaded is not None
    assert loaded.voucher_id == "V-PERSIST-1"
    assert loaded.total_amount == v.total_amount


@pytest.mark.asyncio
async def test_persistent_repo_approval_reload():
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    storage_file = temp_dir / f"vouchers-{uuid.uuid4().hex}.json"
    approval = ApprovalRecord(
        voucher_id="V-A1",
        department="财务部",
        account_code="6601",
        amount=Decimal("1200"),
        approval_status=ApprovalStatus.APPROVED,
        created_at=datetime(2024, 5, 1),
    )
    repo = VoucherRepository(storage_path=str(storage_file))
    await repo.add_approval(approval)

    reloaded = VoucherRepository(storage_path=str(storage_file))
    matches = await reloaded.get_similar_approvals(
        "财务部",
        "6601",
        (Decimal("1000"), Decimal("1300")),
    )
    assert len(matches) == 1
    assert matches[0].voucher_id == "V-A1"
