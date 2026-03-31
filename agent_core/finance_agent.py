"""
agent_core/finance_agent.py
Finance Agent - Claude Agent SDK 集成骨架。

协调工具调用流程：OCR → Ticket_Parser → Tax_Calculator → Account_Classifier → 凭证生成。
调用 Compliance_Checker 和 Approval_Advisor 进行合规检查和审批建议。

NOTE: 这是一个骨架/桩实现，因为我们没有实际的 Claude Agent SDK。
重点在于结构和工具注册/协调流程。
"""
import logging
from decimal import Decimal
from typing import Optional

from agent_core.config import AgentConfig
from agent_core.models import (
    AgentAction,
    AgentRequest,
    AgentResponse,
    ClassifyResult,
    ComplianceResult,
    ParsedTicket,
    TaxResult,
    UserIdentity,
    VoucherDraft,
)

logger = logging.getLogger(__name__)


class FinanceAgent:
    """
    基于 Claude Agent SDK 的核心财务报销智能代理。

    负责协调 OCR 识别、科目分类、凭证生成等工具调用。
    这是一个骨架实现，展示工具注册和协调流程结构。
    """

    # Tool names registered with the Agent SDK
    TOOL_NAMES = [
        "tax_calculator",
        "ocr_service",
        "account_classifier",
        "voucher_generator",
        "ticket_parser",
        "batch_processor",
    ]

    # Extension module names
    EXTENSION_NAMES = [
        "compliance_checker",
        "approval_advisor",
        "budget_checker",
    ]

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._tools: dict[str, object] = {}
        self._extensions: dict[str, object] = {}
        logger.info("FinanceAgent initialized with model=%s", config.model)

    def register_tool(self, name: str, tool: object) -> None:
        """Register a tool instance for use during processing."""
        self._tools[name] = tool
        logger.info("Tool registered: %s", name)

    def register_extension(self, name: str, extension: object) -> None:
        """Register an extension module (compliance, approval, budget)."""
        self._extensions[name] = extension
        logger.info("Extension registered: %s", name)

    def get_registered_tools(self) -> list[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def get_registered_extensions(self) -> list[str]:
        """Return list of registered extension names."""
        return list(self._extensions.keys())

    async def process_reimbursement(
        self,
        request: AgentRequest,
        session_context: dict,
        user_identity: Optional[UserIdentity] = None,
    ) -> AgentResponse:
        """
        Process a single invoice reimbursement request.

        Orchestrates the tool call flow:
        1. OCR_Service: recognize invoice image
        2. Ticket_Parser: parse OCR text into structured ticket
        3. Tax_Calculator: compute tax breakdown
        4. Account_Classifier: match accounting category
        5. Voucher_Generator: generate voucher draft
        6. Compliance_Checker: validate compliance rules
        7. Approval_Advisor: generate approval recommendation

        NOTE: This is a skeleton. Actual Claude Agent SDK integration
        would use the SDK's tool-calling mechanism.
        """
        steps_completed: list[str] = []
        errors: list[str] = []

        try:
            # Step 1: OCR recognition
            ocr_result = await self._call_ocr(request)
            if ocr_result:
                steps_completed.append("ocr")

            # Step 2: Ticket parsing
            parsed_ticket = await self._call_ticket_parser(ocr_result)
            if parsed_ticket:
                steps_completed.append("ticket_parser")

            # Step 3: Tax calculation
            tax_result = await self._call_tax_calculator(parsed_ticket)
            if tax_result:
                steps_completed.append("tax_calculator")

            # Step 4: Account classification
            classify_result = await self._call_account_classifier(parsed_ticket)
            if classify_result:
                steps_completed.append("account_classifier")

            # Step 5: Voucher generation
            voucher_draft = await self._call_voucher_generator(
                parsed_ticket, tax_result, classify_result, user_identity
            )
            if voucher_draft:
                steps_completed.append("voucher_generator")

            # Step 6: Compliance check
            compliance_result = await self._call_compliance_checker(voucher_draft)
            if compliance_result:
                steps_completed.append("compliance_checker")

            # Step 7: Approval advice
            approval_advice = await self._call_approval_advisor(voucher_draft)
            if approval_advice:
                steps_completed.append("approval_advisor")

            return AgentResponse(
                success=True,
                reply=f"报销处理完成，已完成步骤: {', '.join(steps_completed)}",
                action=AgentAction.PREVIEW,
                voucher_data=voucher_draft,
                errors=errors,
            )

        except Exception as e:
            logger.error("Reimbursement processing error: %s", str(e))
            return AgentResponse(
                success=False,
                reply=f"报销处理失败: {str(e)}",
                action=AgentAction.ERROR,
                errors=[str(e)],
            )

    async def _call_ocr(self, request: AgentRequest) -> Optional[dict]:
        """Step 1: Call OCR service to recognize invoice image."""
        ocr = self._tools.get("ocr_service")
        if not ocr or not request.images:
            return None
        # Skeleton: actual implementation would call ocr.recognize()
        logger.info("OCR step: %d images to process", len(request.images))
        return None

    async def _call_ticket_parser(self, ocr_result: Optional[dict]) -> Optional[ParsedTicket]:
        """Step 2: Parse OCR text into structured ticket."""
        parser = self._tools.get("ticket_parser")
        if not parser or not ocr_result:
            return None
        # Skeleton: actual implementation would call parser.parse()
        logger.info("Ticket parser step")
        return None

    async def _call_tax_calculator(self, ticket: Optional[ParsedTicket]) -> Optional[TaxResult]:
        """Step 3: Calculate tax breakdown."""
        calculator = self._tools.get("tax_calculator")
        if not calculator or not ticket:
            return None
        # Skeleton: actual implementation would call calculate_tax()
        logger.info("Tax calculator step")
        return None

    async def _call_account_classifier(self, ticket: Optional[ParsedTicket]) -> Optional[ClassifyResult]:
        """Step 4: Classify accounting category."""
        classifier = self._tools.get("account_classifier")
        if not classifier or not ticket:
            return None
        # Skeleton: actual implementation would call classifier.classify()
        logger.info("Account classifier step")
        return None

    async def _call_voucher_generator(
        self,
        ticket: Optional[ParsedTicket],
        tax_result: Optional[TaxResult],
        classify_result: Optional[ClassifyResult],
        user_identity: Optional[UserIdentity] = None,
    ) -> Optional[VoucherDraft]:
        """Step 5: Generate voucher draft."""
        generator = self._tools.get("voucher_generator")
        if not generator:
            return None
        # Skeleton: actual implementation would call generator.generate_draft()
        logger.info("Voucher generator step")
        return None

    async def _call_compliance_checker(self, voucher: Optional[VoucherDraft]) -> Optional[ComplianceResult]:
        """Step 6: Check compliance rules."""
        checker = self._extensions.get("compliance_checker")
        if not checker or not voucher:
            return None
        # Skeleton: actual implementation would call checker.check()
        logger.info("Compliance checker step")
        return None

    async def _call_approval_advisor(self, voucher: Optional[VoucherDraft]) -> Optional[dict]:
        """Step 7: Generate approval recommendation."""
        advisor = self._extensions.get("approval_advisor")
        if not advisor or not voucher:
            return None
        # Skeleton: actual implementation would call advisor.advise()
        logger.info("Approval advisor step")
        return None
