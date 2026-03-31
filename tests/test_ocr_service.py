"""
tests/test_ocr_service.py
OCR_Service 的属性测试

Feature: finance-agent-architecture-upgrade
"""
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from tools.ocr_service import OCRService, OCRConfig
from agent_core.models import OCRMode


# ── Helper: create an OCRService instance for testing _validate_intranet_url ──

def _make_service() -> OCRService:
    """Create an OCRService with a valid intranet config for testing."""
    config = OCRConfig(
        preferred_mode=OCRMode.CLOUD_VL,
        cloud_url="http://192.168.1.100:8868/ocr",
    )
    return OCRService(config)


# ── Hypothesis strategies for Property 3 ──

# Generate intranet IPs in private ranges
_intranet_ip_strategy = st.one_of(
    # 10.0.0.0/8
    st.tuples(
        st.just(10),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=1, max_value=254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
    # 172.16.0.0/12
    st.tuples(
        st.just(172),
        st.integers(min_value=16, max_value=31),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=1, max_value=254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
    # 192.168.0.0/16
    st.tuples(
        st.just(192),
        st.just(168),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=1, max_value=254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
    # 127.0.0.0/8
    st.tuples(
        st.just(127),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=1, max_value=254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
)

# Generate intranet domain names
_intranet_domain_strategy = st.one_of(
    # *.local, *.internal, *.intranet, *.corp, *.lan, *.private
    st.tuples(
        st.text(
            alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
            min_size=1,
            max_size=10,
        ),
        st.sampled_from([".local", ".internal", ".intranet", ".corp", ".lan", ".private"]),
    ).map(lambda t: f"{t[0]}{t[1]}"),
    # localhost
    st.just("localhost"),
)

# Generate port numbers
_port_strategy = st.integers(min_value=1, max_value=65535)

# Generate URL paths
_path_strategy = st.sampled_from(["", "/ocr", "/api/v1/ocr", "/predict"])

# Build full intranet URLs from IP addresses
_intranet_ip_url_strategy = st.tuples(
    st.sampled_from(["http"]),
    _intranet_ip_strategy,
    _port_strategy,
    _path_strategy,
).map(lambda t: f"{t[0]}://{t[1]}:{t[2]}{t[3]}")

# Build full intranet URLs from domain names
_intranet_domain_url_strategy = st.tuples(
    st.sampled_from(["http"]),
    _intranet_domain_strategy,
    _port_strategy,
    _path_strategy,
).map(lambda t: f"{t[0]}://{t[1]}:{t[2]}{t[3]}")

# Combined intranet URL strategy
_intranet_url_strategy = st.one_of(
    _intranet_ip_url_strategy,
    _intranet_domain_url_strategy,
)

# Generate external (public) IPs - avoid private ranges
_external_ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=1, max_value=254),
).filter(
    lambda t: (
        t[0] != 10
        and not (t[0] == 172 and 16 <= t[1] <= 31)
        and not (t[0] == 192 and t[1] == 168)
        and t[0] != 127
        and t[0] != 0
        and t[0] != 255
    )
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")

# Generate external domain names (public domains)
_external_domain_strategy = st.tuples(
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
        min_size=1,
        max_size=10,
    ),
    st.sampled_from([".com", ".org", ".net", ".io", ".cn", ".edu"]),
).map(lambda t: f"{t[0]}{t[1]}")

# Build full external URLs from IP addresses
_external_ip_url_strategy = st.tuples(
    st.sampled_from(["http", "https"]),
    _external_ip_strategy,
    _port_strategy,
    _path_strategy,
).map(lambda t: f"{t[0]}://{t[1]}:{t[2]}{t[3]}")

# Build full external URLs from domain names
_external_domain_url_strategy = st.tuples(
    st.sampled_from(["http", "https"]),
    _external_domain_strategy,
    _port_strategy,
    _path_strategy,
).map(lambda t: f"{t[0]}://{t[1]}:{t[2]}{t[3]}")

# Combined external URL strategy
_external_url_strategy = st.one_of(
    _external_ip_url_strategy,
    _external_domain_url_strategy,
)


# ── Property 3: 内网地址校验 ──
# Feature: finance-agent-architecture-upgrade, Property 3: 内网地址校验


class TestProperty3IntranetUrlValidation:
    """
    Property 3: 内网地址校验

    For any URL string, OCR_Service's address validation function returns True
    for intranet addresses (private IP ranges 10.x.x.x, 172.16-31.x.x,
    192.168.x.x, 127.x.x.x, or intranet domains), and False for external addresses.

    **Validates: Requirements 2.1, 2.4**
    """

    @given(url=_intranet_url_strategy)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_intranet_urls_return_true(self, url: str):
        """
        For any generated intranet URL (private IP or intranet domain),
        _validate_intranet_url must return True.

        **Validates: Requirements 2.1, 2.4**
        """
        service = _make_service()
        assert service._validate_intranet_url(url) is True, (
            f"Expected True for intranet URL: {url}"
        )

    @given(url=_external_url_strategy)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_external_urls_return_false(self, url: str):
        """
        For any generated external URL (public IP or public domain),
        _validate_intranet_url must return False.

        **Validates: Requirements 2.1, 2.4**
        """
        service = _make_service()
        assert service._validate_intranet_url(url) is False, (
            f"Expected False for external URL: {url}"
        )


# ── Property 7: OCR 降级与恢复 ──
# Feature: finance-agent-architecture-upgrade, Property 7: OCR 降级与恢复

import asyncio
from unittest.mock import AsyncMock, patch

from tools.ocr_service import OCRUnavailableError


# Strategies for Property 7

# Random error types that cloud service might throw
_cloud_error_strategy = st.sampled_from([
    TimeoutError("Cloud OCR request timed out"),
    ConnectionError("Cannot connect to cloud OCR service"),
    OSError("Network unreachable"),
    RuntimeError("Cloud OCR internal error"),
    Exception("Unknown cloud error"),
])

# Random image bytes (small, just for testing)
_image_bytes_strategy = st.binary(min_size=1, max_size=256)

# Random filenames
_filename_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
    min_size=1,
    max_size=20,
).map(lambda s: f"{s}.png")

# Random OCR text that local service returns
_ocr_text_strategy = st.text(min_size=1, max_size=200)


class TestProperty7OCRFallbackAndRecovery:
    """
    Property 7: OCR 降级与恢复

    For any OCR request, when cloud mode returns an error or timeout,
    OCR_Service should automatically use local mode to complete recognition,
    and the result should have mode_used == LOCAL. After fallback, the next
    call should try cloud first.

    **Validates: Requirements 4.4, 4.6**
    """

    @given(
        cloud_error=_cloud_error_strategy,
        image_bytes=_image_bytes_strategy,
        filename=_filename_strategy,
        local_text=_ocr_text_strategy,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cloud_failure_falls_back_to_local(
        self,
        cloud_error: Exception,
        image_bytes: bytes,
        filename: str,
        local_text: str,
    ):
        """
        When cloud OCR raises any error, recognize() should fallback to local
        mode and return OCRResult with mode_used == LOCAL.

        **Validates: Requirements 4.4**
        """
        config = OCRConfig(
            preferred_mode=OCRMode.AUTO,
            cloud_url="http://192.168.1.100:8868/ocr",
            retry_count=0,  # No retries for cleaner test
        )
        service = OCRService(config)

        async def run():
            with patch.object(
                service, "_call_cloud", new_callable=AsyncMock, side_effect=cloud_error
            ), patch.object(
                service, "_call_local", new_callable=AsyncMock, return_value=local_text
            ):
                result = await service.recognize(image_bytes, filename)

            assert result.mode_used == OCRMode.LOCAL, (
                f"Expected mode_used=LOCAL after cloud error ({type(cloud_error).__name__}), "
                f"got {result.mode_used}"
            )
            assert result.raw_text == local_text
            assert result.char_count == len(local_text)
            assert result.elapsed_ms >= 0

        asyncio.run(run())

    @given(
        cloud_error=_cloud_error_strategy,
        image_bytes=_image_bytes_strategy,
        filename=_filename_strategy,
        local_text=_ocr_text_strategy,
        cloud_text=_ocr_text_strategy,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_recovery_tries_cloud_first_after_fallback(
        self,
        cloud_error: Exception,
        image_bytes: bytes,
        filename: str,
        local_text: str,
        cloud_text: str,
    ):
        """
        After a fallback to local mode, the next call should try cloud first.
        If cloud recovers, mode_used should be REMOTE.

        **Validates: Requirements 4.6**
        """
        config = OCRConfig(
            preferred_mode=OCRMode.AUTO,
            cloud_url="http://192.168.1.100:8868/ocr",
            retry_count=0,
        )
        service = OCRService(config)

        async def run():
            # Step 1: Cloud fails → fallback to local
            mock_cloud_fail = AsyncMock(side_effect=cloud_error)
            mock_local = AsyncMock(return_value=local_text)

            with patch.object(service, "_call_cloud", mock_cloud_fail), \
                 patch.object(service, "_call_local", mock_local):
                result1 = await service.recognize(image_bytes, filename)

            assert result1.mode_used == OCRMode.LOCAL, (
                "First call should fallback to LOCAL"
            )
            assert service.is_in_fallback, (
                "Service should be in fallback state after cloud failure"
            )

            # Step 2: Cloud recovers → should try cloud first and succeed
            mock_cloud_ok = AsyncMock(return_value=cloud_text)
            mock_local2 = AsyncMock(return_value=local_text)

            with patch.object(service, "_call_cloud", mock_cloud_ok), \
                 patch.object(service, "_call_local", mock_local2):
                result2 = await service.recognize(image_bytes, filename)

            assert result2.mode_used == OCRMode.REMOTE, (
                "Second call should use REMOTE after recovery"
            )
            assert result2.raw_text == cloud_text
            # Cloud was called (tried first)
            mock_cloud_ok.assert_called_once()
            # Fallback state should be cleared after cloud recovery
            assert not service.is_in_fallback, (
                "Fallback state should be cleared after cloud recovery"
            )

        asyncio.run(run())


# ── Property 8: OCR 结果元数据完整性 ──
# Feature: finance-agent-architecture-upgrade, Property 8: OCR 结果元数据完整性


# Strategies for Property 8

# Random image data for OCR input
_p8_image_bytes_strategy = st.binary(min_size=1, max_size=256)

# Random filenames for OCR input
_p8_filename_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
    min_size=1,
    max_size=20,
).map(lambda s: f"{s}.png")

# Random OCR text returned by mocked backends
_p8_ocr_text_strategy = st.text(min_size=0, max_size=500)

# Which mode to mock as succeeding
_p8_mode_strategy = st.sampled_from([OCRMode.REMOTE, OCRMode.LOCAL])


class TestProperty8OCRResultMetadataCompleteness:
    """
    Property 8: OCR 结果元数据完整性

    For any successful OCR recognition result, mode_used must be one of
    OCRMode.REMOTE or OCRMode.LOCAL, elapsed_ms must be a non-negative
    integer, and char_count must equal len(raw_text).

    **Validates: Requirements 4.7**
    """

    @given(
        preferred_mode=_p8_mode_strategy,
        image_bytes=_p8_image_bytes_strategy,
        filename=_p8_filename_strategy,
        ocr_text=_p8_ocr_text_strategy,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_successful_result_metadata_completeness(
        self,
        preferred_mode: OCRMode,
        image_bytes: bytes,
        filename: str,
        ocr_text: str,
    ):
        """
        Mock either cloud or local to succeed based on preferred_mode,
        call recognize(), and verify:
        - mode_used is OCRMode.REMOTE or OCRMode.LOCAL
        - elapsed_ms >= 0 and is an integer
        - char_count == len(raw_text)

        **Validates: Requirements 4.7**
        """
        config = OCRConfig(
            preferred_mode=preferred_mode,
            cloud_url="http://192.168.1.100:8868/ocr",
            retry_count=0,
        )
        service = OCRService(config)

        async def run():
            with patch.object(
                service, "_call_cloud", new_callable=AsyncMock, return_value=ocr_text
            ), patch.object(
                service, "_call_local", new_callable=AsyncMock, return_value=ocr_text
            ):
                result = await service.recognize(image_bytes, filename)

            # mode_used must be one of the two valid modes
            assert result.mode_used in (OCRMode.REMOTE, OCRMode.LOCAL), (
                f"mode_used must be REMOTE or LOCAL, got {result.mode_used}"
            )

            # elapsed_ms must be a non-negative integer
            assert isinstance(result.elapsed_ms, int), (
                f"elapsed_ms must be an int, got {type(result.elapsed_ms).__name__}"
            )
            assert result.elapsed_ms >= 0, (
                f"elapsed_ms must be non-negative, got {result.elapsed_ms}"
            )

            # char_count must match len(raw_text)
            assert result.char_count == len(result.raw_text), (
                f"char_count ({result.char_count}) must equal len(raw_text) ({len(result.raw_text)})"
            )

        asyncio.run(run())

    @given(
        image_bytes=_p8_image_bytes_strategy,
        filename=_p8_filename_strategy,
        ocr_text=_p8_ocr_text_strategy,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fallback_result_metadata_completeness(
        self,
        image_bytes: bytes,
        filename: str,
        ocr_text: str,
    ):
        """
        When cloud fails and local succeeds (fallback scenario),
        verify the same metadata properties hold.

        **Validates: Requirements 4.7**
        """
        config = OCRConfig(
            preferred_mode=OCRMode.AUTO,
            cloud_url="http://192.168.1.100:8868/ocr",
            retry_count=0,
        )
        service = OCRService(config)

        async def run():
            with patch.object(
                service, "_call_cloud", new_callable=AsyncMock,
                side_effect=TimeoutError("Cloud timeout"),
            ), patch.object(
                service, "_call_local", new_callable=AsyncMock, return_value=ocr_text
            ):
                result = await service.recognize(image_bytes, filename)

            # mode_used must be one of the two valid modes
            assert result.mode_used in (OCRMode.REMOTE, OCRMode.LOCAL), (
                f"mode_used must be REMOTE or LOCAL, got {result.mode_used}"
            )

            # elapsed_ms must be a non-negative integer
            assert isinstance(result.elapsed_ms, int), (
                f"elapsed_ms must be an int, got {type(result.elapsed_ms).__name__}"
            )
            assert result.elapsed_ms >= 0, (
                f"elapsed_ms must be non-negative, got {result.elapsed_ms}"
            )

            # char_count must match len(raw_text)
            assert result.char_count == len(result.raw_text), (
                f"char_count ({result.char_count}) must equal len(raw_text) ({len(result.raw_text)})"
            )

        asyncio.run(run())


# ── Unit Tests: OCR_Service 边界情况 (Task 5.5) ──
# 需求: 2.1, 4.8


class TestOCRServiceIntranetUrlExamples:
    """
    单元测试：内网地址格式示例验证

    测试具体的内网地址返回 True，外网地址返回 False。

    **Validates: Requirements 2.1**
    """

    def test_10_network_returns_true(self):
        service = _make_service()
        assert service._validate_intranet_url("http://10.0.0.1:8868/ocr") is True

    def test_172_16_network_returns_true(self):
        service = _make_service()
        assert service._validate_intranet_url("http://172.16.0.1:8868/ocr") is True

    def test_192_168_network_returns_true(self):
        service = _make_service()
        assert service._validate_intranet_url("http://192.168.1.100:8868/ocr") is True

    def test_127_loopback_returns_true(self):
        service = _make_service()
        assert service._validate_intranet_url("http://127.0.0.1:8868/ocr") is True

    def test_localhost_returns_true(self):
        service = _make_service()
        assert service._validate_intranet_url("http://localhost:8868/ocr") is True

    def test_local_domain_returns_true(self):
        service = _make_service()
        assert service._validate_intranet_url("http://server.local:8868/ocr") is True

    def test_external_ip_8888_returns_false(self):
        service = _make_service()
        assert service._validate_intranet_url("http://8.8.8.8:8868/ocr") is False

    def test_external_domain_google_returns_false(self):
        service = _make_service()
        assert service._validate_intranet_url("http://google.com:8868/ocr") is False

    def test_external_domain_example_returns_false(self):
        service = _make_service()
        assert service._validate_intranet_url("http://example.com:8868/ocr") is False


class TestOCRServiceExternalUrlRejection:
    """
    单元测试：外网地址配置拒绝

    创建 OCRService 时使用外网 URL 应抛出 ValueError。

    **Validates: Requirements 2.1, 2.4**
    """

    def test_external_ip_raises_value_error(self):
        config = OCRConfig(
            preferred_mode=OCRMode.CLOUD_VL,
            cloud_url="http://8.8.8.8:8868/ocr",
        )
        with pytest.raises(ValueError, match="内网地址"):
            OCRService(config)

    def test_external_domain_raises_value_error(self):
        config = OCRConfig(
            preferred_mode=OCRMode.CLOUD_VL,
            cloud_url="https://google.com/ocr",
        )
        with pytest.raises(ValueError, match="内网地址"):
            OCRService(config)

    def test_external_example_domain_raises_value_error(self):
        config = OCRConfig(
            preferred_mode=OCRMode.CLOUD_VL,
            cloud_url="https://example.com/api/ocr",
        )
        with pytest.raises(ValueError, match="内网地址"):
            OCRService(config)


class TestOCRServiceBothModesUnavailable:
    """
    单元测试：云端和本地模式均不可用时的错误消息

    **Validates: Requirements 4.8**
    """

    def test_both_modes_unavailable_raises_ocr_unavailable_error(self):
        config = OCRConfig(
            preferred_mode=OCRMode.AUTO,
            cloud_url="http://192.168.1.100:8868/ocr",
            retry_count=0,
        )
        service = OCRService(config)

        async def run():
            with patch.object(
                service, "_call_cloud", new_callable=AsyncMock,
                side_effect=ConnectionError("Cloud down"),
            ), patch.object(
                service, "_call_local", new_callable=AsyncMock,
                side_effect=RuntimeError("Local model not loaded"),
            ):
                with pytest.raises(OCRUnavailableError, match="OCR 服务完全不可用，请联系运维"):
                    await service.recognize(b"fake_image", "test.png")

        asyncio.run(run())

    def test_both_modes_unavailable_error_message_content(self):
        config = OCRConfig(
            preferred_mode=OCRMode.AUTO,
            cloud_url="http://192.168.1.100:8868/ocr",
            retry_count=0,
        )
        service = OCRService(config)

        async def run():
            with patch.object(
                service, "_call_cloud", new_callable=AsyncMock,
                side_effect=TimeoutError("Cloud timeout"),
            ), patch.object(
                service, "_call_local", new_callable=AsyncMock,
                side_effect=FileNotFoundError("Model file missing"),
            ):
                try:
                    await service.recognize(b"fake_image", "test.png")
                    pytest.fail("Expected OCRUnavailableError")
                except OCRUnavailableError as e:
                    assert e.message == "OCR 服务完全不可用，请联系运维"
                    assert str(e) == "OCR 服务完全不可用，请联系运维"

        asyncio.run(run())
