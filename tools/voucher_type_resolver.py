"""
tools/voucher_type_resolver.py
凭证类型解析器：规则优先，RAG 次之，LLM 最后兜底。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_VOUCHER_TYPES = {"记", "收", "付", "转", "调", "冲", "费用", "成本", "收入", "税务"}

_ALIAS_TO_TYPE = {
    "记": "记",
    "记账": "记",
    "记账凭证": "记",
    "收": "收",
    "收款": "收",
    "收款凭证": "收",
    "付": "付",
    "付款": "付",
    "付款凭证": "付",
    "转": "转",
    "转账": "转",
    "转账凭证": "转",
    "调": "调",
    "调整": "调",
    "调整凭证": "调",
    "冲": "冲",
    "红字冲销": "冲",
    "红字冲销凭证": "冲",
    "费用": "费用",
    "费用凭证": "费用",
    "成本": "成本",
    "成本凭证": "成本",
    "收入": "收入",
    "收入凭证": "收入",
    "税务": "税务",
    "税务凭证": "税务",
}

_RULES: list[tuple[str, list[str]]] = [
    ("税务", ["税", "进项", "销项", "增值税", "附加税"]),
    ("收入", ["收入", "销售", "营业收入", "主营业务收入"]),
    ("成本", ["成本", "主营业务成本", "生产成本"]),
    ("费用", ["费用", "报销", "差旅", "采购", "办公", "交通", "招待", "会议", "福利"]),
    ("收", ["收款", "到账", "回款", "收回"]),
    ("付", ["付款", "支付", "代付", "请款"]),
    ("转", ["结转", "转账", "划转", "内部转移"]),
    ("调", ["调整", "调账", "更正"]),
    ("冲", ["冲销", "红字", "冲回"]),
]


class VoucherTypeResolver:
    def __init__(
        self,
        rag_enabled: bool = False,
        rag_knowledge_base_dir: str = "./rag/knowledge_base",
        rag_knowledge_file: str = "voucher_type_rules.json",
        rag_min_score: float = 0.4,
        enable_llm_fallback: bool = True,
    ) -> None:
        self._rag_enabled = rag_enabled
        self._rag_knowledge_base_dir = Path(rag_knowledge_base_dir)
        self._rag_knowledge_file = rag_knowledge_file
        self._rag_min_score = rag_min_score
        self._enable_llm_fallback = enable_llm_fallback
        self._rag_rules_cache: list[dict] | None = None

    def resolve(self, voucher_data: dict) -> str:
        context = self._build_context(voucher_data)

        by_rule = self._resolve_by_rule(context)
        if by_rule is not None:
            return by_rule

        if self._rag_enabled:
            by_rag = self._resolve_by_rag(context)
            if by_rag is not None:
                return by_rag

        if self._enable_llm_fallback:
            by_llm = self._resolve_by_llm_hint(voucher_data)
            if by_llm is not None:
                return by_llm

        return "记"

    def _build_context(self, voucher_data: dict) -> str:
        texts: list[str] = [
            str(voucher_data.get("summary") or ""),
            str(voucher_data.get("usage") or ""),
            str(voucher_data.get("memo") or ""),
            str(voucher_data.get("remark") or ""),
        ]
        for entry in voucher_data.get("entries") or []:
            if isinstance(entry, dict):
                texts.append(str(entry.get("account_name") or ""))
                texts.append(str(entry.get("account_code") or ""))
        return " ".join(t for t in texts if t).strip()

    def _resolve_by_rule(self, context: str) -> str | None:
        if not context:
            return None
        for voucher_type, keywords in _RULES:
            if any(kw in context for kw in keywords):
                return voucher_type
        return None

    def _resolve_by_rag(self, context: str) -> str | None:
        if not context:
            return None

        rules = self._load_rag_rules()
        if not rules:
            return None

        best_type: str | None = None
        best_score = 0.0
        for item in rules:
            raw_type = str(item.get("voucher_type") or "").strip()
            voucher_type = self._normalize_type(raw_type)
            if voucher_type is None:
                continue
            keywords = [str(k).strip() for k in item.get("keywords", []) if str(k).strip()]
            if not keywords:
                continue
            matched = sum(1 for kw in keywords if kw in context)
            score = matched / len(keywords)
            if score > best_score:
                best_score = score
                best_type = voucher_type

        if best_type is not None and best_score >= self._rag_min_score:
            return best_type
        return None

    def _resolve_by_llm_hint(self, voucher_data: dict) -> str | None:
        for field in (
            "voucher_type",
            "type",
            "llm_voucher_type",
            "suggested_voucher_type",
            "predicted_voucher_type",
        ):
            value = str(voucher_data.get(field) or "").strip()
            normalized = self._normalize_type(value)
            if normalized is not None:
                return normalized
        return None

    def _normalize_type(self, raw_type: str) -> str | None:
        if not raw_type:
            return None
        if raw_type in SUPPORTED_VOUCHER_TYPES:
            return raw_type
        return _ALIAS_TO_TYPE.get(raw_type)

    def _load_rag_rules(self) -> list[dict]:
        if self._rag_rules_cache is not None:
            return self._rag_rules_cache

        file_path = self._rag_knowledge_base_dir / self._rag_knowledge_file
        if not file_path.exists():
            self._rag_rules_cache = []
            return self._rag_rules_cache

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._rag_rules_cache = [item for item in data if isinstance(item, dict)]
            else:
                self._rag_rules_cache = []
        except Exception as exc:
            logger.warning("Failed to load voucher type RAG knowledge file %s: %s", file_path, exc)
            self._rag_rules_cache = []
        return self._rag_rules_cache
