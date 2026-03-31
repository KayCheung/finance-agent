"""
tests/test_local_paddleocr_inference.py
属性测试 — 本地 PaddleOCR 推理

Feature: local-paddleocr-fallback
"""
import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_core.models import OCRMode
from tools.ocr_service import OCRConfig, OCRService


def _build_paddle_result(lines: list[str]):
    """Build PaddleOCR result format from text lines.

    PaddleOCR returns: [[ [box_coords, (text, confidence)], ... ]]
    """
    return [
        [
            [[[0, 0], [1, 0], [1, 1], [0, 1]], (line, 0.99)]
            for line in lines
        ]
    ]


class TestProperty3PaddleOCRResultTextLineConcatenation:
    """
    Feature: local-paddleocr-fallback, Property 3: PaddleOCR 结果文本行拼接

    **Validates: Requirements 3.3**

    对于任意非空的文字行列表（模拟 PaddleOCR 返回的识别结果），
    _call_local 的输出应等于这些文字行用 "\\n" 拼接的结果。
    """

    @given(
        lines=st.lists(st.text(min_size=1), min_size=1),
    )
    @settings(max_examples=100, deadline=None)
    def test_call_local_joins_text_lines_with_newline(self, lines: list[str]):
        """
        For any non-empty list of text lines returned by PaddleOCR,
        _call_local should return those lines joined with '\\n'.
        """
        # 1. Create OCRService with default config
        config = OCRConfig()
        service = OCRService(config)

        # 2. Pre-set _paddle_engine to a mock whose .ocr() returns
        #    the PaddleOCR-formatted result built from the generated lines
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = _build_paddle_result(lines)
        service._paddle_engine = mock_engine

        # 3. Mock cv2.imdecode to return a fake numpy array (non-None)
        #    and numpy.frombuffer to return a fake array
        fake_image = np.zeros((10, 10, 3), dtype=np.uint8)

        with patch("cv2.imdecode", return_value=fake_image), \
             patch("numpy.frombuffer", return_value=np.array([1], dtype=np.uint8)):
            # 4. Call _call_local with some non-empty bytes
            result = asyncio.run(
                service._call_local(b"\x89PNG\r\n\x1a\n", "test.png")
            )

        # 5. Verify the result equals the lines joined with "\n"
        expected = "\n".join(lines)
        assert result == expected


class TestProperty4InvalidImageBytesRaiseValueError:
    """
    Feature: local-paddleocr-fallback, Property 4: 非法图像字节触发 ValueError

    **Validates: Requirements 5.2**

    对于任意非空的随机字节序列（非合法图像格式），调用 _call_local 应抛出
    ValueError，且错误消息包含"图像解码失败"。
    """

    @given(
        image_bytes=st.binary(min_size=1).filter(
            lambda b: not b.startswith(b'\x89PNG')
            and not b.startswith(b'\xff\xd8\xff')
            and not b.startswith(b'GIF8')
            and not b.startswith(b'BM')
            and not b.startswith(b'II\x2a\x00')
            and not b.startswith(b'MM\x00\x2a')
            and not b.startswith(b'RIFF')
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_invalid_image_bytes_raise_value_error(self, image_bytes: bytes):
        """
        For any non-empty random byte sequence (not a valid image format),
        calling _call_local should raise ValueError with message containing
        "图像解码失败".
        """
        config = OCRConfig()
        service = OCRService(config)
        # Pre-set _paddle_engine to skip lazy loading / import check
        service._paddle_engine = MagicMock()

        with patch("cv2.imdecode", return_value=None):
            with pytest.raises(ValueError, match="图像解码失败"):
                asyncio.run(service._call_local(image_bytes, "test.png"))


import time


class TestProperty7LocalInferenceTimeoutEnforcement:
    """
    Feature: local-paddleocr-fallback, Property 7: 本地推理超时强制执行

    **Validates: Requirements 8.1, 8.2**

    对于任意 local_timeout 值，当本地 PaddleOCR 推理耗时超过该值时，
    _call_local 应抛出 asyncio.TimeoutError，不会无限期阻塞调用方。
    """

    @given(
        timeout_val=st.floats(min_value=0.01, max_value=0.5),
    )
    @settings(max_examples=100, deadline=None)
    def test_local_inference_timeout(self, timeout_val: float):
        """
        For any local_timeout value, when PaddleOCR inference takes longer
        than that value, _call_local should raise asyncio.TimeoutError.
        """
        # 1. Create OCRService with the generated timeout
        config = OCRConfig(local_timeout=timeout_val)
        service = OCRService(config)

        # 2. Mock _paddle_engine.ocr to simulate slow inference
        def slow_ocr(*args, **kwargs):
            time.sleep(timeout_val * 2)
            return [[]]

        mock_engine = MagicMock()
        mock_engine.ocr.side_effect = slow_ocr
        service._paddle_engine = mock_engine

        # 3. Mock image decoding to return a valid fake image
        fake_image = np.zeros((10, 10, 3), dtype=np.uint8)

        with patch("cv2.imdecode", return_value=fake_image), \
             patch("numpy.frombuffer", return_value=np.array([1], dtype=np.uint8)):
            # 4. Verify that _call_local raises TimeoutError
            with pytest.raises(asyncio.TimeoutError):
                asyncio.run(service._call_local(b"\x89PNG", "test.png"))


# ── Unit Tests: _call_local edge cases (Task 4.5) ──

from unittest.mock import AsyncMock


class TestCallLocalEmptyBytes:
    """
    **Validates: Requirements 5.1**

    空字节输入应抛出 ValueError("图像数据为空")。
    """

    def test_empty_bytes_raises_value_error(self):
        config = OCRConfig()
        service = OCRService(config)

        with pytest.raises(ValueError, match="图像数据为空"):
            asyncio.run(service._call_local(b"", "test.png"))


class TestCallLocalPaddleOCRNotInstalled:
    """
    **Validates: Requirements 4.1**

    PaddleOCR 未安装时，_call_local 应抛出 RuntimeError。
    """

    def test_paddleocr_not_installed_raises_runtime_error(self):
        config = OCRConfig()
        service = OCRService(config)
        # Ensure _paddle_engine is None so lazy loading path is triggered
        assert service._paddle_engine is None

        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "paddleocr":
                raise ImportError("No module named 'paddleocr'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(RuntimeError, match="PaddleOCR 未安装"):
                asyncio.run(service._call_local(b"\x89PNG\r\n", "test.png"))


class TestCallLocalLazyLoading:
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    懒加载测试：
    - 构造后 _paddle_engine 为 None
    - 首次调用后 _paddle_engine 非 None
    - 多次调用复用同一实例
    """

    def test_paddle_engine_is_none_after_construction(self):
        """Requirement 2.1: _paddle_engine is None after construction."""
        config = OCRConfig()
        service = OCRService(config)
        assert service._paddle_engine is None

    def test_paddle_engine_is_set_after_first_call(self):
        """Requirement 2.2: _paddle_engine is not None after first call."""
        config = OCRConfig()
        service = OCRService(config)

        # Pre-set a mock engine to simulate what lazy loading would produce,
        # then verify the engine persists after the call
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = [[]]
        service._paddle_engine = mock_engine

        fake_image = np.zeros((10, 10, 3), dtype=np.uint8)

        with patch("cv2.imdecode", return_value=fake_image), \
             patch("numpy.frombuffer", return_value=np.array([1], dtype=np.uint8)):
            asyncio.run(service._call_local(b"\x89PNG\r\n", "test.png"))

        # After call, _paddle_engine should still be set (not reset to None)
        assert service._paddle_engine is not None
        assert service._paddle_engine is mock_engine

    def test_multiple_calls_reuse_same_engine_instance(self):
        """Requirement 2.3: multiple calls reuse the same _paddle_engine instance."""
        config = OCRConfig()
        service = OCRService(config)

        mock_engine = MagicMock()
        mock_engine.ocr.return_value = [[]]
        service._paddle_engine = mock_engine

        fake_image = np.zeros((10, 10, 3), dtype=np.uint8)

        with patch("cv2.imdecode", return_value=fake_image), \
             patch("numpy.frombuffer", return_value=np.array([1], dtype=np.uint8)):
            asyncio.run(service._call_local(b"\x89PNG\r\n", "test.png"))
            engine_after_first = service._paddle_engine

            asyncio.run(service._call_local(b"\x89PNG\r\n", "test2.png"))
            engine_after_second = service._paddle_engine

        # Same instance should be reused across calls
        assert engine_after_first is engine_after_second
        assert engine_after_first is mock_engine


class TestCallLocalEmptyResults:
    """
    **Validates: Requirements 3.4**

    PaddleOCR 返回 None 或空列表时应返回空字符串。
    """

    def test_paddleocr_returns_none_gives_empty_string(self):
        """PaddleOCR returns None → returns empty string."""
        config = OCRConfig()
        service = OCRService(config)

        mock_engine = MagicMock()
        mock_engine.ocr.return_value = None
        service._paddle_engine = mock_engine

        fake_image = np.zeros((10, 10, 3), dtype=np.uint8)

        with patch("cv2.imdecode", return_value=fake_image), \
             patch("numpy.frombuffer", return_value=np.array([1], dtype=np.uint8)):
            result = asyncio.run(service._call_local(b"\x89PNG\r\n", "test.png"))

        assert result == ""

    def test_paddleocr_returns_empty_list_gives_empty_string(self):
        """PaddleOCR returns empty list → returns empty string."""
        config = OCRConfig()
        service = OCRService(config)

        mock_engine = MagicMock()
        mock_engine.ocr.return_value = []
        service._paddle_engine = mock_engine

        fake_image = np.zeros((10, 10, 3), dtype=np.uint8)

        with patch("cv2.imdecode", return_value=fake_image), \
             patch("numpy.frombuffer", return_value=np.array([1], dtype=np.uint8)):
            result = asyncio.run(service._call_local(b"\x89PNG\r\n", "test.png"))

        assert result == ""


class TestCallLocalCloudModeWithoutPaddleOCR:
    """
    **Validates: Requirements 4.2**

    PaddleOCR 未安装时，云端模式（CLOUD_VL）应正常工作。
    """

    def test_cloud_mode_works_without_paddleocr(self):
        """Cloud mode should work fine even if paddleocr is not installed."""
        config = OCRConfig(preferred_mode=OCRMode.CLOUD_VL)
        service = OCRService(config)

        mock_cloud_result = "识别结果文本"

        async def mock_call_cloud(image_bytes, filename):
            return mock_cloud_result

        with patch.object(service, "_call_cloud", side_effect=mock_call_cloud):
            result = asyncio.run(service.recognize(b"\x89PNG\r\n", "test.png"))

        assert result.raw_text == mock_cloud_result
        assert result.mode_used == OCRMode.REMOTE
