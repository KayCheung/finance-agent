"""
tests/test_voucher_generator.py
VoucherGenerator 单元测试
"""
import re
from decimal import Decimal

import pytest

from tools.voucher_generator import VoucherGenerator


@pytest.fixture
def gen():
    return VoucherGenerator()


class TestGenerateId:
    def test_format(self, gen):
        vid = gen.generate_id()
        assert re.match(r"^VOU-\d{8}-[A-F0-9]{6}$", vid)

    def test_unique(self, gen):
        ids = {gen.generate_id() for _ in range(100)}
        assert len(ids) == 100


class TestGenerateDraft:
    def test_single_invoice_balanced(self, gen):
        draft = gen.generate_draft(
            department="技术部",
            submitter="张三",
            usage="差旅费",
            account_code="6602.02",
            account_name="差旅费-火车票",
            amount=Decimal("429.50"),
            summary="技术部-张三-差旅费",
        )
        assert draft.balanced is True
        assert draft.total_debit == draft.total_credit == Decimal("429.50")
        assert len(draft.entries) == 2
        assert draft.entries[0].debit == Decimal("429.50")
        assert draft.entries[1].credit == Decimal("429.50")
        assert draft.entries[1].account_name == "其他应付款-张三"

    def test_voucher_id_format(self, gen):
        draft = gen.generate_draft(
            department="财务部", submitter="李四", usage="办公用品",
            account_code="6602.01", account_name="办公费",
            amount=Decimal("100"), summary="test",
        )
        assert re.match(r"^VOU-\d{8}-[A-F0-9]{6}$", draft.voucher_id)


class TestGenerateMergedDraft:
    def test_merge_same_account(self, gen):
        items = [
            {"account_code": "6602.02", "account_name": "差旅费", "amount": Decimal("100"), "summary": "票1"},
            {"account_code": "6602.02", "account_name": "差旅费", "amount": Decimal("200"), "summary": "票2"},
        ]
        draft = gen.generate_merged_draft("技术部", "张三", "差旅费", items)
        assert draft.balanced is True
        assert draft.total_debit == draft.total_credit == Decimal("300")
        # Same account aggregated: 1 debit + 1 credit
        assert len(draft.entries) == 2
        assert draft.entries[0].debit == Decimal("300")

    def test_merge_different_accounts(self, gen):
        items = [
            {"account_code": "6602.02", "account_name": "差旅费", "amount": Decimal("100"), "summary": "票1"},
            {"account_code": "6602.01", "account_name": "办公费", "amount": Decimal("50"), "summary": "票2"},
        ]
        draft = gen.generate_merged_draft("技术部", "张三", "报销", items)
        assert draft.balanced is True
        assert draft.total_debit == draft.total_credit == Decimal("150")
        # 2 debit entries + 1 credit entry
        assert len(draft.entries) == 3
        credit_entry = draft.entries[-1]
        assert credit_entry.credit == Decimal("150")

    def test_merge_summaries_joined(self, gen):
        items = [
            {"account_code": "6602.02", "account_name": "差旅费", "amount": Decimal("100"), "summary": "出差北京"},
            {"account_code": "6602.02", "account_name": "差旅费", "amount": Decimal("200"), "summary": "出差上海"},
        ]
        draft = gen.generate_merged_draft("技术部", "张三", "差旅费", items)
        assert "出差北京" in draft.summary
        assert "出差上海" in draft.summary


class TestToMcpMessage:
    def test_mcp_format(self, gen):
        draft = gen.generate_draft(
            department="技术部", submitter="张三", usage="差旅费",
            account_code="6602.02", account_name="差旅费-火车票",
            amount=Decimal("429.50"), summary="技术部-张三-差旅费",
        )
        msg = gen.to_mcp_message(draft)
        assert msg["protocol"] == "MCP/1.0"
        assert msg["voucher_type"] == "expense_reimbursement"
        assert msg["voucher_id"] == draft.voucher_id
        assert msg["status"] == "pending_approval"
        assert msg["total_amount"] == 429.50
        assert len(msg["entries"]) == 2
