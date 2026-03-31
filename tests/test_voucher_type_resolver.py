from pathlib import Path
import uuid

from tools.voucher_type_resolver import VoucherTypeResolver


def test_rule_first_overrides_llm_hint():
    resolver = VoucherTypeResolver(rag_enabled=False, enable_llm_fallback=True)
    voucher = {
        "summary": "后勤部采购办公用品报销",
        "usage": "办公报销",
        "voucher_type": "转",
    }
    # 规则命中“报销/办公”应优先返回“费用”，而不是 LLM 提示的“转”
    assert resolver.resolve(voucher) == "费用"


def test_rag_fallback_when_rule_not_hit():
    kb = Path("tests/.tmp") / f"kb-{uuid.uuid4().hex}"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "voucher_type_rules.json").write_text(
        '[{"voucher_type":"调","keywords":["调账","更正"]}]',
        encoding="utf-8",
    )
    resolver = VoucherTypeResolver(
        rag_enabled=True,
        rag_knowledge_base_dir=str(kb),
        rag_min_score=0.5,
        enable_llm_fallback=False,
    )
    voucher = {
        "summary": "本月期末调账处理",
        "usage": "更正历史分录",
    }
    assert resolver.resolve(voucher) == "调"


def test_llm_fallback_when_rule_and_rag_miss():
    resolver = VoucherTypeResolver(
        rag_enabled=False,
        enable_llm_fallback=True,
    )
    voucher = {
        "summary": "常规处理",
        "usage": "内部核算",
        "voucher_type": "费用凭证",
    }
    assert resolver.resolve(voucher) == "费用"


def test_default_to_ji_when_all_miss():
    resolver = VoucherTypeResolver(
        rag_enabled=False,
        enable_llm_fallback=False,
    )
    voucher = {
        "summary": "常规处理",
        "usage": "内部核算",
    }
    assert resolver.resolve(voucher) == "记"
