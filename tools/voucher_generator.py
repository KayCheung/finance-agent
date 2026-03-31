"""
tools/voucher_generator.py
凭证生成器 - 封装凭证草稿生成和 MCP 标准报文生成逻辑。

支持单张发票凭证生成和批量合并凭证生成（同科目发票金额汇总，
多条借方分录，借贷总额平衡）。
"""
import uuid
from datetime import datetime
from decimal import Decimal

from agent_core.models import VoucherDraft, VoucherEntry


class VoucherGenerator:
    """凭证草稿生成器，支持单张和合并凭证。"""

    def generate_id(self) -> str:
        """Generate voucher ID in VOU-YYYYMMDD-XXXXXX format."""
        date_part = datetime.now().strftime("%Y%m%d")
        random_part = uuid.uuid4().hex[:6].upper()
        return f"VOU-{date_part}-{random_part}"

    def generate_draft(
        self,
        department: str,
        submitter: str,
        usage: str,
        account_code: str,
        account_name: str,
        amount: Decimal,
        summary: str,
    ) -> VoucherDraft:
        """Generate a single-invoice voucher draft.

        Creates one debit entry for the expense account and one credit
        entry for 其他应付款 (other payables) to the submitter.
        """
        debit_entry = VoucherEntry(
            account_code=account_code,
            account_name=account_name,
            debit=amount,
            credit=Decimal("0"),
        )
        credit_entry = VoucherEntry(
            account_code="2241",
            account_name=f"其他应付款-{submitter}",
            debit=Decimal("0"),
            credit=amount,
        )
        return VoucherDraft(
            voucher_id=self.generate_id(),
            summary=summary,
            department=department,
            submitter=submitter,
            usage=usage,
            entries=[debit_entry, credit_entry],
            total_debit=amount,
            total_credit=amount,
            balanced=True,
        )

    def generate_merged_draft(
        self,
        department: str,
        submitter: str,
        usage: str,
        items: list[dict],
    ) -> VoucherDraft:
        """Generate a merged voucher draft from multiple invoices.

        Args:
            items: list of dicts, each with keys:
                - account_code: str
                - account_name: str
                - amount: Decimal
                - summary: str

        Same-account invoices are aggregated into a single debit entry.
        A single credit entry balances the total.
        """
        # Aggregate amounts by account (code, name)
        aggregated: dict[tuple[str, str], Decimal] = {}
        summaries: list[str] = []
        for item in items:
            key = (item["account_code"], item["account_name"])
            aggregated[key] = aggregated.get(key, Decimal("0")) + item["amount"]
            if item.get("summary"):
                summaries.append(item["summary"])

        # Build debit entries
        entries: list[VoucherEntry] = []
        total = Decimal("0")
        for (code, name), amt in aggregated.items():
            entries.append(VoucherEntry(
                account_code=code,
                account_name=name,
                debit=amt,
                credit=Decimal("0"),
            ))
            total += amt

        # Single credit entry
        entries.append(VoucherEntry(
            account_code="2241",
            account_name=f"其他应付款-{submitter}",
            debit=Decimal("0"),
            credit=total,
        ))

        merged_summary = "; ".join(summaries) if summaries else f"{department}-{submitter}-{usage}"

        return VoucherDraft(
            voucher_id=self.generate_id(),
            summary=merged_summary,
            department=department,
            submitter=submitter,
            usage=usage,
            entries=entries,
            total_debit=total,
            total_credit=total,
            balanced=True,
        )

    def to_mcp_message(self, draft: VoucherDraft) -> dict:
        """Convert a VoucherDraft to MCP standard message format."""
        return {
            "protocol": "MCP/1.0",
            "voucher_type": "expense_reimbursement",
            "voucher_id": draft.voucher_id,
            "created_at": datetime.now().isoformat(),
            "summary": draft.summary,
            "department": draft.department,
            "submitter": draft.submitter,
            "entries": [
                {
                    "account_code": e.account_code,
                    "account_name": e.account_name,
                    "debit": float(e.debit),
                    "credit": float(e.credit),
                }
                for e in draft.entries
            ],
            "total_amount": float(draft.total_debit),
            "status": "pending_approval",
        }
