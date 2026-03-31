"""
tests/test_local_paddleocr_routing.py
属性测试 — 单模式路由隔离

Feature: local-paddleocr-fallback
"""
import asyncio
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_core.models import OCRMode
from tools.ocr_service import OCRConfig, OCRService


class TestProperty5SingleModeRoutingIsolation:
    """
    Feature: local-paddleocr-fallback, Property 5: 单模式路由隔离

    **Validates: Requirements 7.4, 7.5**

    对于任意 preferred_mode 为 LOCAL、REMOTE 或 CLOUD_VL 的 OCRService 实例，
    以及任意有效图像字节，recognize() 应仅调用该模式对应的后端
    （LOCAL → _call_local，REMOTE/CLOUD_VL → _call_cloud），绝不调用另一个后端。
    """

    @given(
        mode=st.sampled_from([OCRMode.LOCAL, OCRMode.REMOTE, OCRMode.CLOUD_VL]),
        image_bytes=st.binary(min_size=1, max_size=256),
        ocr_text=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=100, deadline=None)
    def test_single_mode_only_calls_corresponding_backend(
        self, mode, image_bytes, ocr_text
    ):
        config = OCRConfig(preferred_mode=mode)
        service = OCRService(config)

        mock_cloud = AsyncMock(return_value=ocr_text)
        mock_local = AsyncMock(return_value=ocr_text)

        async def run():
            with patch.object(service, "_call_cloud", mock_cloud), \
                 patch.object(service, "_call_local", mock_local):
                result = await service.recognize(image_bytes, "test.png")

            if mode == OCRMode.LOCAL:
                mock_local.assert_called_once()
                mock_cloud.assert_not_called()
                assert result.mode_used == OCRMode.LOCAL
            else:  # REMOTE or CLOUD_VL
                mock_cloud.assert_called()
                mock_local.assert_not_called()
                assert result.mode_used == OCRMode.REMOTE

        asyncio.run(run())


class TestProperty6AutoModeCloudFailureFallback:
    """
    Feature: local-paddleocr-fallback, Property 6: AUTO 模式云端失败自动降级

    **Validates: Requirements 7.3**

    对于任意有效图像字节，当 preferred_mode 为 AUTO 且云端调用抛出异常时，
    recognize() 应降级到本地推理并返回 mode_used == LOCAL 的 OCRResult。
    """

    @given(
        image_bytes=st.binary(min_size=1, max_size=256),
        cloud_error=st.sampled_from([
            TimeoutError("cloud timeout"),
            ConnectionError("connection refused"),
            RuntimeError("cloud internal error"),
            Exception("unknown cloud error"),
        ]),
        local_text=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=100, deadline=None)
    def test_auto_mode_falls_back_to_local_on_cloud_failure(
        self, image_bytes, cloud_error, local_text
    ):
        config = OCRConfig(preferred_mode=OCRMode.AUTO, retry_count=0)
        service = OCRService(config)

        mock_cloud = AsyncMock(side_effect=cloud_error)
        mock_local = AsyncMock(return_value=local_text)

        async def run():
            with patch.object(service, "_call_cloud", mock_cloud), \
                 patch.object(service, "_call_local", mock_local):
                result = await service.recognize(image_bytes, "test.png")

            assert result.mode_used == OCRMode.LOCAL
            assert result.raw_text == local_text
            mock_cloud.assert_called_once()
            mock_local.assert_called_once()

        asyncio.run(run())


from agent_core.config import OCRConfig as AppOCRConfig


class TestRoutingAndModeSwitchingEdgeCases:
    """
    单元测试 — 路由与模式切换边界情况

    **Validates: Requirements 7.1, 7.2, 7.6, 7.7**
    """

    def test_local_mode_paddleocr_not_installed_raises_ocr_unavailable(self):
        """
        LOCAL 模式 + PaddleOCR 未安装 → OCRUnavailableError

        Validates: Requirements 7.6
        """
        import pytest
        from tools.ocr_service import OCRUnavailableError

        config = OCRConfig(preferred_mode=OCRMode.LOCAL)
        service = OCRService(config)

        mock_local = AsyncMock(side_effect=RuntimeError("PaddleOCR 未安装"))

        async def run():
            with patch.object(service, "_call_local", mock_local):
                with pytest.raises(OCRUnavailableError):
                    await service.recognize(b"\x89PNG\r\n", "test.png")

        asyncio.run(run())

    def test_remote_mode_cloud_unavailable_raises_ocr_unavailable(self):
        """
        REMOTE 模式 + 云端不可用 → OCRUnavailableError

        Validates: Requirements 7.7
        """
        import pytest
        from tools.ocr_service import OCRUnavailableError

        config = OCRConfig(preferred_mode=OCRMode.REMOTE, retry_count=0)
        service = OCRService(config)

        mock_cloud = AsyncMock(side_effect=ConnectionError("connection refused"))

        async def run():
            with patch.object(service, "_call_cloud", mock_cloud):
                with pytest.raises(OCRUnavailableError):
                    await service.recognize(b"\x89PNG\r\n", "test.png")

        asyncio.run(run())

    def test_ocr_mode_enum_contains_four_values(self):
        """
        OCRMode 枚举应包含 AUTO、LOCAL、REMOTE、CLOUD_VL 四个值

        Validates: Requirements 7.1
        """
        members = set(OCRMode.__members__.keys())
        assert members == {"AUTO", "LOCAL", "REMOTE", "CLOUD_VL"}

        assert OCRMode.AUTO.value == "auto"
        assert OCRMode.LOCAL.value == "local"
        assert OCRMode.REMOTE.value == "remote"
        assert OCRMode.CLOUD_VL.value == "cloud_vl"

    def test_preferred_mode_default_is_auto(self):
        """
        preferred_mode 默认值应为 "auto" / OCRMode.AUTO

        Validates: Requirements 7.2
        """
        # 应用层 OCRConfig (Pydantic)
        app_config = AppOCRConfig()
        assert app_config.preferred_mode == "auto"

        # 服务层 OCRConfig (dataclass)
        service_config = OCRConfig()
        assert service_config.preferred_mode == OCRMode.AUTO
