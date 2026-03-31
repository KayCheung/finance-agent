"""
agent_core/models.py
共享数据模型（Pydantic）- 所有模块共用的数据结构定义
"""
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime, date
from enum import Enum
from typing import Optional


# ── 价税分离 ──

class TaxResult(BaseModel):
    total_amount: Decimal
    tax_rate: Decimal
    amount_without_tax: Decimal
    tax_amount: Decimal
    balanced: bool = Field(description="amount_without_tax + tax_amount == total_amount")


# ── OCR ──

class OCRMode(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    REMOTE = "remote"
    CLOUD_VL = "cloud_vl"  # 向后兼容别名，等价于 REMOTE



class OCRResult(BaseModel):
    raw_text: str
    mode_used: OCRMode
    elapsed_ms: int
    char_count: int


# ── 票据 ──

class TicketType(str, Enum):
    VAT_SPECIAL = "vat_special"    # 增值税专用发票
    VAT_NORMAL = "vat_normal"      # 增值税普通发票
    ELECTRONIC = "electronic"      # 电子发票
    TRAIN = "train"                # 火车票
    FLIGHT = "flight"              # 机票行程单
    TAXI = "taxi"                  # 出租车票
    TOLL = "toll"                  # 过路费发票
    UNKNOWN = "unknown"            # 未知类型


class ParsedTicket(BaseModel):
    ticket_type: TicketType
    fields: dict
    raw_text: str
    validation_errors: list[str] = []


# ── 科目匹配 ──

class ClassifyStrategy(str, Enum):
    RAG = "rag"
    LLM = "llm"
    KEYWORD = "keyword"


class ClassifyResult(BaseModel):
    account_code: str
    account_name: str
    strategy_used: ClassifyStrategy
    confidence: float
    fallback_path: list[ClassifyStrategy] = []


# ── 凭证 ──

class VoucherEntry(BaseModel):
    account_code: str
    account_name: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")


class VoucherDraft(BaseModel):
    voucher_id: str
    summary: str
    department: str
    submitter: str
    usage: str
    entries: list[VoucherEntry]
    total_debit: Decimal
    total_credit: Decimal
    balanced: bool


# ── OA 对接（需在 VoucherRecord 之前定义）──

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"


class SubmitResult(BaseModel):
    success: bool
    approval_id: Optional[str] = None
    error: Optional[str] = None


class VoucherRecord(BaseModel):
    """持久化凭证记录（VoucherRepository 存储）"""
    voucher_id: str
    created_at: datetime
    department: str
    submitter: str
    summary: str
    usage: str
    entries: list[VoucherEntry]
    total_amount: Decimal
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approval_id: Optional[str] = None
    expense_type: str = ""  # 费用类型分类（如 "差旅费"、"交通费"），由 Account_Classifier 匹配结果填充
    source_tickets: list[ParsedTicket] = []
    session_id: Optional[str] = None


# ── 会话 ──

class SessionSummary(BaseModel):
    session_id: str
    created_at: datetime
    last_active: datetime
    voucher_count: int = 0
    message_count: int = 0
    title: str = ""
    preview: str = ""
    pinned: bool = False
    archived: bool = False


class SessionData(BaseModel):
    session_id: str
    created_at: datetime
    last_active: datetime
    messages: list[dict] = []
    voucher_state: Optional[dict] = None
    metadata: dict = {}


# ── 批量处理 ──

class InvoiceStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class BatchItemResult(BaseModel):
    index: int
    filename: str
    status: InvoiceStatus
    ticket: Optional[ParsedTicket] = None
    error: Optional[str] = None


class BatchResult(BaseModel):
    total: int
    success_count: int
    failed_count: int = Field(description="包含 FAILED、TIMEOUT、REJECTED 三种状态的发票总数")
    voucher_count: int
    total_amount: Decimal = Field(description="所有识别成功的发票含税总额之和（不含失败/拒绝的发票）")
    items: list[BatchItemResult]


# ── Agent 核心 ──

class AgentMode(str, Enum):
    STANDALONE = "standalone"    # 自带 HTTP 网关
    EMBEDDED = "embedded"        # 作为子 Agent


class CapabilityDeclaration(BaseModel):
    """Agent 能力声明，供 Orchestrator 发现和调用"""
    agent_name: str = "finance-reimbursement-agent"
    description: str = "企业财务报销智能代理"
    supported_intents: list[str] = [
        "invoice_reimbursement",
        "voucher_query",
        "batch_reimbursement",
    ]
    input_schema: dict = {}
    output_schema: dict = {}


class UserIdentity(BaseModel):
    user_id: str
    department: str
    role: str


class AgentRequest(BaseModel):
    intent: str
    session_id: Optional[str] = None
    session_context: Optional[dict] = None
    user_identity: Optional[UserIdentity] = None
    message: Optional[str] = None
    images: list[dict] = []
    parameters: dict = {}

    class AgentMode(str, Enum):
        STANDALONE = "standalone"    # 自带 HTTP 网关
        EMBEDDED = "embedded"        # 作为子 Agent


    class CapabilityDeclaration(BaseModel):
        """Agent 能力声明，供 Orchestrator 发现和调用"""
        agent_name: str = "finance-reimbursement-agent"
        description: str = "企业财务报销智能代理"
        supported_intents: list[str] = [
            "invoice_reimbursement",
            "voucher_query",
            "batch_reimbursement",
        ]
        input_schema: dict = {}
        output_schema: dict = {}





class AgentAction(str, Enum):
    NONE = "none"           # 普通对话，无凭证操作
    PREVIEW = "preview"     # 凭证草稿预览
    POSTED = "posted"       # 凭证已提交
    ERROR = "error"         # 处理失败


class AgentResponse(BaseModel):
    success: bool
    reply: str
    action: AgentAction = AgentAction.NONE
    voucher_data: Optional[dict] = None
    mcp_voucher: Optional[dict] = None
    batch_result: Optional[BatchResult] = None
    errors: list[str] = []


# ── 合规与审批 ──

class ComplianceViolation(BaseModel):
    rule_name: str
    description: str
    policy_reference: str


class ComplianceResult(BaseModel):
    passed: bool
    violations: list[ComplianceViolation] = []


class ApprovalRecommendation(str, Enum):
    APPROVE = "approve"
    ATTENTION = "attention"
    REJECT = "reject"


class BudgetResult(BaseModel):
    enabled: bool                                    # Budget_Checker 是否启用
    passed: bool                                     # 是否通过预算校验（未启用时为 True）
    department: str = ""
    budget_remaining: Optional[Decimal] = None       # 部门剩余预算
    voucher_amount: Optional[Decimal] = None         # 凭证金额
    overspend_amount: Optional[Decimal] = None       # 超支金额（仅超支时有值）
    warning_message: Optional[str] = None            # 超支警告信息


class ApprovalAdvice(BaseModel):
    recommendation: ApprovalRecommendation
    reason: str
    similar_cases_count: int
    approval_rate: float


class ApprovalRecord(BaseModel):
    """历史审批记录，供 VoucherRepository.get_similar_approvals 返回使用"""
    voucher_id: str
    department: str
    account_code: str
    amount: Decimal
    approval_status: ApprovalStatus
    created_at: datetime
