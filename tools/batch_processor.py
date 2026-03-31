"""
tools/batch_processor.py
批量报销处理模块 - 并发控制 + 超时管理 + 图片大小校验

支持多张发票的并行 OCR 识别、按票据类型和科目分组、
合并或分别生成凭证。

需求: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 6.9, 6.10, 6.11
"""
import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from agent_core.models import (
    BatchItemResult,
    BatchResult,
    InvoiceStatus,
)
from tools.ocr_service import OCRService
from tools.ticket_parser import TicketParser

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """批量处理配置"""
    max_concurrency: int = 3
    total_timeout: int = 300       # seconds
    max_image_size_mb: int = 10


@dataclass
class ImageInput:
    """单张发票图片输入"""
    index: int
    filename: str
    data: bytes


class BatchProcessor:
    """
    批量报销处理器。

    行为:
    1. 校验每张图片 base64 大小（> max_image_size_mb → REJECTED）
    2. asyncio.Semaphore 控制 OCR 并发度
    3. asyncio.wait_for 控制总超时
    4. 失败的跳过，继续处理其余
    5. 按票据类型和科目分组，支持 merge/separate 策略
    """

    def __init__(
        self,
        ocr: OCRService,
        parser: TicketParser,
        config: BatchConfig | None = None,
    ):
        self._ocr = ocr
        self._parser = parser
        self._config = config or BatchConfig()

    @property
    def config(self) -> BatchConfig:
        return self._config

    async def process(
        self,
        images: list[ImageInput],
        strategy: str = "separate",
    ) -> BatchResult:
        """
        批量处理发票图片。

        Args:
            images: 发票图片列表
            strategy: 凭证生成策略，"merge" 合并同科目 或 "separate" 分别生成

        Returns:
            BatchResult 包含处理摘要和每张发票的结果
        """
        items: list[BatchItemResult] = []
        semaphore = asyncio.Semaphore(self._config.max_concurrency)

        async def _guarded_process(image: ImageInput) -> BatchItemResult:
            """Semaphore-guarded single image processing."""
            async with semaphore:
                return await self._process_single(image)

        # Pre-validate image sizes; reject oversized ones immediately
        tasks: list[asyncio.Task] = []
        rejected: list[BatchItemResult] = []

        max_bytes = self._config.max_image_size_mb * 1024 * 1024

        for image in images:
            if len(image.data) > max_bytes:
                rejected.append(BatchItemResult(
                    index=image.index,
                    filename=image.filename,
                    status=InvoiceStatus.REJECTED,
                    error=f"图片大小 {len(image.data) / (1024*1024):.2f}MB 超过限制 {self._config.max_image_size_mb}MB",
                ))
            else:
                tasks.append(asyncio.create_task(_guarded_process(image)))

        # Execute all valid tasks with total timeout
        if tasks:
            try:
                completed = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self._config.total_timeout,
                )
                for result in completed:
                    if isinstance(result, Exception):
                        # Shouldn't normally happen since _process_single catches errors,
                        # but handle just in case
                        logger.error("批量处理任务异常: %s", result)
                    else:
                        items.append(result)
            except asyncio.TimeoutError:
                logger.warning("批量处理总超时 (%ds)，终止未完成任务", self._config.total_timeout)
                # Collect completed results and mark remaining as timeout
                for task in tasks:
                    if task.done() and not task.cancelled():
                        try:
                            result = task.result()
                        except Exception as exc:
                            logger.error("超时前任务异常: %s", exc)
                            continue
                        if isinstance(result, Exception):
                            logger.error("超时前任务异常: %s", result)
                        else:
                            items.append(result)
                    elif not task.done():
                        task.cancel()
                        # We don't know which image this task corresponds to,
                        # so timeout items will be added below

        # Combine rejected + processed items, sort by index
        all_items = rejected + items
        # Identify indices that were processed
        processed_indices = {item.index for item in all_items}

        # Mark any images that weren't processed (due to timeout) as TIMEOUT
        for image in images:
            if image.index not in processed_indices:
                all_items.append(BatchItemResult(
                    index=image.index,
                    filename=image.filename,
                    status=InvoiceStatus.TIMEOUT,
                    error=f"批量处理总超时 ({self._config.total_timeout}s)",
                ))

        all_items.sort(key=lambda x: x.index)

        # Calculate summary
        success_count = sum(1 for i in all_items if i.status == InvoiceStatus.SUCCESS)
        failed_count = sum(
            1 for i in all_items
            if i.status in (InvoiceStatus.FAILED, InvoiceStatus.TIMEOUT, InvoiceStatus.REJECTED)
        )

        # Total amount from successful items
        total_amount = Decimal("0")
        for item in all_items:
            if item.status == InvoiceStatus.SUCCESS and item.ticket:
                amount_str = item.ticket.fields.get("total") or item.ticket.fields.get("ticket_price") or item.ticket.fields.get("amount") or "0"
                try:
                    total_amount += Decimal(str(amount_str))
                except Exception:
                    pass

        # Group by ticket type and account for voucher count
        voucher_count = self._calculate_voucher_count(all_items, strategy)

        return BatchResult(
            total=len(images),
            success_count=success_count,
            failed_count=failed_count,
            voucher_count=voucher_count,
            total_amount=total_amount,
            items=all_items,
        )

    async def _process_single(self, image: ImageInput) -> BatchItemResult:
        """
        处理单张发票：OCR 识别 → 票据解析。

        失败时返回 FAILED 状态和错误信息，不抛出异常。
        """
        try:
            # OCR recognition
            ocr_result = await self._ocr.recognize(image.data, image.filename)

            # Parse ticket from OCR text
            ticket = self._parser.parse(ocr_result.raw_text)

            return BatchItemResult(
                index=image.index,
                filename=image.filename,
                status=InvoiceStatus.SUCCESS,
                ticket=ticket,
            )
        except Exception as e:
            logger.warning(
                "发票 %s (index=%d) 处理失败: %s",
                image.filename,
                image.index,
                str(e),
            )
            return BatchItemResult(
                index=image.index,
                filename=image.filename,
                status=InvoiceStatus.FAILED,
                error=str(e),
            )

    def _calculate_voucher_count(
        self,
        items: list[BatchItemResult],
        strategy: str,
    ) -> int:
        """
        根据策略计算生成凭证数。

        - "separate": 每张成功发票生成一张凭证
        - "merge": 按票据类型分组，每组生成一张凭证
        """
        success_items = [i for i in items if i.status == InvoiceStatus.SUCCESS and i.ticket]

        if not success_items:
            return 0

        if strategy == "merge":
            # Group by ticket_type — each group produces one voucher
            groups: set[str] = set()
            for item in success_items:
                groups.add(item.ticket.ticket_type.value)
            return len(groups)
        else:
            # "separate" — one voucher per successful invoice
            return len(success_items)

    def group_by_type_and_account(
        self,
        items: list[BatchItemResult],
    ) -> dict[str, list[BatchItemResult]]:
        """
        按票据类型分组成功的发票项。

        Returns:
            dict mapping ticket_type value to list of BatchItemResult
        """
        groups: dict[str, list[BatchItemResult]] = {}
        for item in items:
            if item.status == InvoiceStatus.SUCCESS and item.ticket:
                key = item.ticket.ticket_type.value
                groups.setdefault(key, []).append(item)
        return groups
