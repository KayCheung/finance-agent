"""
agent_core/config.py
统一配置加载模块 - 从 YAML 文件读取配置并映射到 Pydantic 模型
"""
import os
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import yaml


# ── OCR 配置 ──

class OCRConfig(BaseModel):
    preferred_mode: str = "auto"
    cloud_url: str = "http://192.168.1.100:8868/ocr"
    cloud_timeout: int = 30
    local_timeout: int = 60
    retry_count: int = 1
    local_lang: str = "ch"
    local_use_angle_cls: bool = True
    local_use_gpu: bool = False
    local_model_dir: Optional[str] = None

    @field_validator("preferred_mode", mode="before")
    @classmethod
    def _lowercase_preferred_mode(cls, v: str) -> str:
        if isinstance(v, str):
            return v.lower()
        return v


# ── 会话配置 ──

class SessionConfig(BaseModel):
    backend_class: str = "storage.backends.file_backend.FileSessionBackend"
    storage_dir: str = "./sessions"


# ── 科目匹配配置 ──

class AccountClassifierConfig(BaseModel):
    strategy_chain: list[str] = ["rag", "llm", "keyword"]
    confidence_threshold: float = 0.7


# ── RAG 配置 ──

class RAGConfig(BaseModel):
    enabled: bool = False
    knowledge_base_dir: str = "./rag/knowledge_base"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_api_url: str = ""
    top_k: int = 3


# ── 批量处理配置 ──

class BatchConfig(BaseModel):
    max_concurrency: int = 3
    total_timeout: int = 300
    max_image_size_mb: int = 10


# ── OA 配置 ──

class OAConfig(BaseModel):
    enabled: bool = False
    api_url: str = ""
    auth_type: str = "bearer"
    auth_credentials: dict = {}
    field_mapping: dict = {}
    use_webhook: bool = True
    webhook_secret: str = ""
    polling_interval: int = 60
    submit_timeout: int = 30


# ── VoucherRepository 配置 ──

class VoucherRepoConfig(BaseModel):
    storage_file: str = "./storage/vouchers.json"


# ── 凭证类型解析配置 ──

class VoucherTypeConfig(BaseModel):
    use_rag_fallback: bool = True
    rag_knowledge_file: str = "voucher_type_rules.json"
    rag_min_score: float = 0.4
    enable_llm_fallback: bool = True


# ── 外部提交通道配置 ──

class SubmissionConfig(BaseModel):
    enabled: bool = False
    channel: str = "oa"                 # oa | accounting(预留)
    retry_count: int = 1
    retry_backoff_ms: int = 300


# ── 合规规则配置 ──

class ComplianceConfig(BaseModel):
    max_single_amount: int = 50000
    max_monthly_by_type: int = 200000
    ticket_validity_days: int = 180


# ── 扩展配置 ──

class ExtensionsConfig(BaseModel):
    enable_budget_check: bool = False
    compliance: ComplianceConfig = ComplianceConfig()


# ── Agent 配置 ──

class AgentConfig(BaseModel):
    mode: str = "standalone"
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 20


# ── 顶层配置 ──

class AppConfig(BaseModel):
    ocr: OCRConfig = OCRConfig()
    session: SessionConfig = SessionConfig()
    account_classifier: AccountClassifierConfig = AccountClassifierConfig()
    rag: RAGConfig = RAGConfig()
    batch: BatchConfig = BatchConfig()
    oa: OAConfig = OAConfig()
    voucher_repo: VoucherRepoConfig = VoucherRepoConfig()
    voucher_type: VoucherTypeConfig = VoucherTypeConfig()
    submission: SubmissionConfig = SubmissionConfig()
    extensions: ExtensionsConfig = ExtensionsConfig()
    agent: AgentConfig = AgentConfig()


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    从 YAML 文件加载配置，映射到 Pydantic 配置模型。
    文件不存在时返回默认配置。
    """
    if not os.path.exists(config_path):
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        return AppConfig()

    return AppConfig(**raw)
