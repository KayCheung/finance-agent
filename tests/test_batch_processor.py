"""
tests/test_batch_processor.py
Batch_Processor 属性测试和单元测试

Feature: finance-agent-architecture-upgrade
"""
import asyncio
import base64
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent_core.models import (
    BatchItemResult,
    BatchResult,
    InvoiceStatus,
    OCRMode,
    OCRResult,
    ParsedTicket,
    TicketType,
)
from tools.batch_processor import BatchConfig, BatchProcessor, ImageInput
from tools.ocr_service import OCRConfig, OCRService
from tools.ticket_parser import TicketParser
from tools.voucher_generator import VoucherGenerator


# ── Helpers ──

def _make_ocr_service() -> OCRService:
    """Create an OCRService with valid intranet config for testing."""
    config = OCRConfig(
        preferred_mode=OCRMode.CLOUD_VL,
        cloud_url="http://192.168.1.100:8868/ocr",
        retry_count=0,
    )
    return OCRService(config)


def _make_batch_processor(
    ocr: OCRService | None = None,
    parser: TicketParser | None = None,
    config: BatchConfig | None = None,
) -> BatchProcessor:
    """Create a BatchProcessor with defaults for testing."""
    return BatchProcessor(
        ocr=ocr or _make_ocr_service(),
        parser=parser or TicketParser(),
        config=config or BatchConfig(),
    )


# Sample OCR text that produces a valid ParsedTicket (VAT normal invoice)
_SAMPLE_OCR_TEXT = (
    "增值税普通发票\n"
    "发票代码：1234567890\n"
    "发票号码：12345678\n"
    "开票日期：2024-01-15\n"
    "购方名称：测试公司\n"
    "销方名称：供应商公司\n"
    "金额：100.00\n"
    "税率：0.13\n"
    "税额：13.00\n"
    "价税合计：113.00\n"
)


# ── Hypothesis strategies ──

# Strategy for number of images in a batch (1 to 20)
_batch_size_strategy = st.integers(min_value=1, max_value=10)

# Strategy for generating a random failure probability (0.0 to 1.0)
_failure_prob_strategy = st.floats(min_value=0.0, max_value=0.8)

# Strategy for random invoice amounts (positive decimals)
_amount_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Strategy for max_concurrency values
_concurrency_strategy = st.integers(min_value=1, max_value=5)


# ══════════════════════════════════════════════════════════════════════
# Property 11: 批量处理摘要一致性 (Task 11.2)
# Feature: finance-agent-architecture-upgrade, Property 11: 批量处理摘要一致性
# ══════════════════════════════════════════════════════════════════════


class TestProperty11BatchProcessingSummaryConsistency:
    """
    Property 11: 批量处理摘要一致性

    For any batch processing result, success_count + failed_count must equal total
    (where failed_count includes FAILED, TIMEOUT, REJECTED statuses).
    All SUCCESS items must have a valid ParsedTicket.
    All non-SUCCESS items must have an error reason.
    Failed invoices must not affect processing of remaining invoices.

    **Validates: Requirements 6.6, 6.7**
    """

    @given(
        num_images=st.integers(min_value=1, max_value=10),
        fail_indices=st.lists(st.integers(min_value=0, max_value=9), max_size=5, unique=True),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_counts_consistency(self, num_images: int, fail_indices: list[int]):
        """
        Generate random number of images with random failures.
        Verify success_count + failed_count == total.
        SUCCESS items have ParsedTicket, non-SUCCESS items have error reason.

        **Validates: Requirements 6.6, 6.7**
        """
        # Clamp fail_indices to valid range
        fail_indices_set = {i for i in fail_indices if i < num_images}

        ocr_service = _make_ocr_service()
        parser = TicketParser()
        processor = _make_batch_processor(ocr=ocr_service, parser=parser)

        images = [
            ImageInput(index=i, filename=f"invoice_{i}.png", data=b"fake_image_data")
            for i in range(num_images)
        ]

        call_count = 0

        async def mock_recognize(image_bytes, filename):
            nonlocal call_count
            # Determine index from filename
            idx = int(filename.split("_")[1].split(".")[0])
            if idx in fail_indices_set:
                raise RuntimeError(f"OCR failed for image {idx}")
            return OCRResult(
                raw_text=_SAMPLE_OCR_TEXT,
                mode_used=OCRMode.REMOTE,
                elapsed_ms=100,
                char_count=len(_SAMPLE_OCR_TEXT),
            )

        async def run():
            with patch.object(ocr_service, "recognize", side_effect=mock_recognize):
                result = await processor.process(images)

            # Core property: success_count + failed_count == total
            assert result.success_count + result.failed_count == result.total, (
                f"success({result.success_count}) + failed({result.failed_count}) "
                f"!= total({result.total})"
            )
            assert result.total == num_images

            # Verify each item
            for item in result.items:
                if item.status == InvoiceStatus.SUCCESS:
                    assert item.ticket is not None, (
                        f"SUCCESS item at index {item.index} must have a ParsedTicket"
                    )
                else:
                    assert item.error is not None and len(item.error) > 0, (
                        f"Non-SUCCESS item at index {item.index} (status={item.status}) "
                        f"must have an error reason"
                    )

        asyncio.run(run())


# ══════════════════════════════════════════════════════════════════════
# Property 12: 合并凭证借贷平衡 (Task 11.3)
# Feature: finance-agent-architecture-upgrade, Property 12: 合并凭证借贷平衡
# ══════════════════════════════════════════════════════════════════════


class TestProperty12MergedVoucherDebitCreditBalance:
    """
    Property 12: 合并凭证借贷平衡

    For any set of invoices using merge strategy, the generated voucher's
    total_debit must equal total_credit, and both must equal the sum of
    all invoice amounts.

    NOTE: This tests VoucherGenerator.generate_merged_draft, not BatchProcessor directly.

    **Validates: Requirements 6.4**
    """

    @given(
        amounts=st.lists(
            st.decimals(
                min_value=Decimal("0.01"),
                max_value=Decimal("99999.99"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_merged_voucher_debit_credit_balance(self, amounts: list[Decimal]):
        """
        Generate random invoice amount lists, verify merged voucher
        total_debit == total_credit == sum of amounts.

        **Validates: Requirements 6.4**
        """
        generator = VoucherGenerator()
        expected_total = sum(amounts)

        items = [
            {
                "account_code": "6602.02",
                "account_name": "差旅费",
                "amount": amt,
                "summary": f"发票{i+1}",
            }
            for i, amt in enumerate(amounts)
        ]

        draft = generator.generate_merged_draft(
            department="技术部",
            submitter="张三",
            usage="差旅费",
            items=items,
        )

        # Core property: debit == credit == sum of amounts
        assert draft.total_debit == draft.total_credit, (
            f"total_debit({draft.total_debit}) != total_credit({draft.total_credit})"
        )
        assert draft.total_debit == expected_total, (
            f"total_debit({draft.total_debit}) != sum_of_amounts({expected_total})"
        )
        assert draft.balanced is True

    @given(
        amounts_per_account=st.lists(
            st.tuples(
                st.sampled_from(["6602.01", "6602.02", "6602.03"]),
                st.sampled_from(["办公费", "差旅费", "交通费"]),
                st.decimals(
                    min_value=Decimal("0.01"),
                    max_value=Decimal("99999.99"),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            ),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_merged_voucher_multi_account_balance(
        self, amounts_per_account: list[tuple[str, str, Decimal]]
    ):
        """
        Generate invoices across multiple accounts, verify merged voucher
        total_debit == total_credit == sum of all amounts.

        **Validates: Requirements 6.4**
        """
        generator = VoucherGenerator()
        expected_total = sum(amt for _, _, amt in amounts_per_account)

        items = [
            {
                "account_code": code,
                "account_name": name,
                "amount": amt,
                "summary": f"发票{i+1}",
            }
            for i, (code, name, amt) in enumerate(amounts_per_account)
        ]

        draft = generator.generate_merged_draft(
            department="技术部",
            submitter="张三",
            usage="报销",
            items=items,
        )

        assert draft.total_debit == draft.total_credit, (
            f"total_debit({draft.total_debit}) != total_credit({draft.total_credit})"
        )
        assert draft.total_debit == expected_total, (
            f"total_debit({draft.total_debit}) != sum_of_amounts({expected_total})"
        )
        assert draft.balanced is True


# ══════════════════════════════════════════════════════════════════════
# Property 13: 批量处理并发度限制 (Task 11.4)
# Feature: finance-agent-architecture-upgrade, Property 13: 批量处理并发度限制
# ══════════════════════════════════════════════════════════════════════


class TestProperty13BatchConcurrencyLimit:
    """
    Property 13: 批量处理并发度限制

    For any batch processing request, the number of concurrent OCR calls
    must not exceed the configured max_concurrency value.

    **Validates: Requirements 6.9**
    """

    @given(
        num_images=st.integers(min_value=3, max_value=10),
        max_concurrency=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_concurrent_count_does_not_exceed_max(
        self, num_images: int, max_concurrency: int
    ):
        """
        Generate large batch requests, monitor concurrent count doesn't
        exceed max_concurrency.

        **Validates: Requirements 6.9**
        """
        ocr_service = _make_ocr_service()
        parser = TicketParser()
        config = BatchConfig(max_concurrency=max_concurrency, total_timeout=60)
        processor = _make_batch_processor(ocr=ocr_service, parser=parser, config=config)

        images = [
            ImageInput(index=i, filename=f"invoice_{i}.png", data=b"fake_image_data")
            for i in range(num_images)
        ]

        # Track concurrency
        current_concurrent = 0
        max_observed_concurrent = 0
        lock = asyncio.Lock()

        async def mock_recognize(image_bytes, filename):
            nonlocal current_concurrent, max_observed_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_observed_concurrent:
                    max_observed_concurrent = current_concurrent

            # Simulate some work
            await asyncio.sleep(0.01)

            async with lock:
                current_concurrent -= 1

            return OCRResult(
                raw_text=_SAMPLE_OCR_TEXT,
                mode_used=OCRMode.REMOTE,
                elapsed_ms=10,
                char_count=len(_SAMPLE_OCR_TEXT),
            )

        async def run():
            nonlocal max_observed_concurrent
            with patch.object(ocr_service, "recognize", side_effect=mock_recognize):
                result = await processor.process(images)

            assert max_observed_concurrent <= max_concurrency, (
                f"Max observed concurrency ({max_observed_concurrent}) exceeded "
                f"max_concurrency ({max_concurrency})"
            )
            assert result.total == num_images

        asyncio.run(run())


# ══════════════════════════════════════════════════════════════════════
# Property 14: 批量处理图片大小限制 (Task 11.5)
# Feature: finance-agent-architecture-upgrade, Property 14: 批量处理图片大小限制
# ══════════════════════════════════════════════════════════════════════


class TestProperty14BatchImageSizeLimit:
    """
    Property 14: 批量处理图片大小限制

    For any base64 encoded data exceeding 10MB, Batch_Processor must reject
    the image and mark its status as REJECTED with a rejection reason.

    **Validates: Requirements 6.11**
    """

    @given(
        oversized_factor=st.floats(min_value=1.01, max_value=2.0),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_oversized_images_are_rejected(self, oversized_factor: float):
        """
        Generate random size base64 data exceeding 10MB, verify images
        are REJECTED.

        **Validates: Requirements 6.11**
        """
        max_size_mb = 10
        config = BatchConfig(max_image_size_mb=max_size_mb)
        ocr_service = _make_ocr_service()
        parser = TicketParser()
        processor = _make_batch_processor(ocr=ocr_service, parser=parser, config=config)

        # Create oversized data (just over the limit)
        oversized_bytes = int(max_size_mb * 1024 * 1024 * oversized_factor)
        large_data = b"\x00" * oversized_bytes

        images = [
            ImageInput(index=0, filename="oversized.png", data=large_data),
        ]

        async def run():
            # OCR should never be called for rejected images
            mock_recognize = AsyncMock()
            with patch.object(ocr_service, "recognize", mock_recognize):
                result = await processor.process(images)

            assert result.total == 1
            assert result.failed_count == 1
            assert result.success_count == 0

            item = result.items[0]
            assert item.status == InvoiceStatus.REJECTED, (
                f"Expected REJECTED for oversized image, got {item.status}"
            )
            assert item.error is not None and len(item.error) > 0, (
                "REJECTED item must have an error reason"
            )
            # OCR should not have been called
            mock_recognize.assert_not_called()

        asyncio.run(run())

    @given(
        size_factor=st.floats(min_value=0.01, max_value=0.99),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_undersized_images_are_not_rejected(self, size_factor: float):
        """
        Images under the size limit should NOT be rejected.

        **Validates: Requirements 6.11**
        """
        max_size_mb = 10
        config = BatchConfig(max_image_size_mb=max_size_mb)
        ocr_service = _make_ocr_service()
        parser = TicketParser()
        processor = _make_batch_processor(ocr=ocr_service, parser=parser, config=config)

        # Create data under the limit
        size_bytes = int(max_size_mb * 1024 * 1024 * size_factor)
        # Ensure at least 1 byte
        size_bytes = max(size_bytes, 1)
        small_data = b"\x00" * size_bytes

        images = [
            ImageInput(index=0, filename="normal.png", data=small_data),
        ]

        async def run():
            with patch.object(
                ocr_service,
                "recognize",
                new_callable=AsyncMock,
                return_value=OCRResult(
                    raw_text=_SAMPLE_OCR_TEXT,
                    mode_used=OCRMode.REMOTE,
                    elapsed_ms=50,
                    char_count=len(_SAMPLE_OCR_TEXT),
                ),
            ):
                result = await processor.process(images)

            assert result.total == 1
            item = result.items[0]
            assert item.status != InvoiceStatus.REJECTED, (
                f"Image under size limit should not be REJECTED, got {item.status}"
            )

        asyncio.run(run())


# ══════════════════════════════════════════════════════════════════════
# Unit Tests: Batch_Processor 边界情况 (Task 11.6)
# 需求: 6.8, 6.10
# ══════════════════════════════════════════════════════════════════════


class TestBatchProcessorCapacity:
    """
    单元测试：20 张发票容量

    **Validates: Requirements 6.8**
    """

    def test_process_20_invoices(self):
        """Batch processor should handle at least 20 invoices."""
        ocr_service = _make_ocr_service()
        parser = TicketParser()
        config = BatchConfig(max_concurrency=5, total_timeout=60)
        processor = _make_batch_processor(ocr=ocr_service, parser=parser, config=config)

        images = [
            ImageInput(index=i, filename=f"invoice_{i}.png", data=b"fake_image_data")
            for i in range(20)
        ]

        async def run():
            with patch.object(
                ocr_service,
                "recognize",
                new_callable=AsyncMock,
                return_value=OCRResult(
                    raw_text=_SAMPLE_OCR_TEXT,
                    mode_used=OCRMode.REMOTE,
                    elapsed_ms=50,
                    char_count=len(_SAMPLE_OCR_TEXT),
                ),
            ):
                result = await processor.process(images)

            assert result.total == 20
            assert result.success_count == 20
            assert result.failed_count == 0
            assert len(result.items) == 20

        asyncio.run(run())


class TestBatchProcessorTimeout:
    """
    单元测试：总超时行为

    **Validates: Requirements 6.10**
    """

    def test_total_timeout_returns_partial_results(self):
        """
        When total timeout is exceeded, completed results should be returned
        and remaining items marked as TIMEOUT.
        """
        ocr_service = _make_ocr_service()
        parser = TicketParser()
        # Very short timeout to trigger timeout behavior
        config = BatchConfig(max_concurrency=1, total_timeout=1)
        processor = _make_batch_processor(ocr=ocr_service, parser=parser, config=config)

        images = [
            ImageInput(index=i, filename=f"invoice_{i}.png", data=b"fake_image_data")
            for i in range(5)
        ]

        async def slow_recognize(image_bytes, filename):
            # Each call takes 2 seconds, with concurrency=1 and timeout=1,
            # not all will complete
            await asyncio.sleep(2)
            return OCRResult(
                raw_text=_SAMPLE_OCR_TEXT,
                mode_used=OCRMode.REMOTE,
                elapsed_ms=2000,
                char_count=len(_SAMPLE_OCR_TEXT),
            )

        async def run():
            with patch.object(ocr_service, "recognize", side_effect=slow_recognize):
                result = await processor.process(images)

            assert result.total == 5
            # Some items should be TIMEOUT
            timeout_items = [
                i for i in result.items if i.status == InvoiceStatus.TIMEOUT
            ]
            assert len(timeout_items) > 0, (
                "Expected some items to be TIMEOUT after total timeout exceeded"
            )
            # success + failed should equal total
            assert result.success_count + result.failed_count == result.total

        asyncio.run(run())


class TestBatchProcessorEmptyBatch:
    """
    单元测试：空批次处理

    **Validates: Requirements 6.8**
    """

    def test_empty_batch_returns_zero_counts(self):
        """Processing an empty batch should return zero counts."""
        processor = _make_batch_processor()

        async def run():
            result = await processor.process([])

            assert result.total == 0
            assert result.success_count == 0
            assert result.failed_count == 0
            assert result.voucher_count == 0
            assert result.total_amount == Decimal("0")
            assert len(result.items) == 0

        asyncio.run(run())
