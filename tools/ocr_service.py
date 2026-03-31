"""
tools/ocr_service.py
OCR 服务统一架构 - 双模式（云端 + 本地）+ 自动降级 + 内网安全约束

需求: 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9
"""
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address, ip_network
from typing import Optional
from urllib.parse import urlparse

from agent_core.models import OCRMode, OCRResult

logger = logging.getLogger(__name__)


class OCRUnavailableError(Exception):
    """云端和本地 OCR 模式均不可用时抛出"""

    def __init__(self, message: str = "OCR 服务完全不可用，请联系运维"):
        self.message = message
        super().__init__(self.message)


# Private IP networks for intranet validation
_PRIVATE_NETWORKS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
]

# Common intranet domain patterns
_INTRANET_DOMAIN_PATTERNS = [
    r"\.local$",
    r"\.internal$",
    r"\.intranet$",
    r"\.corp$",
    r"\.lan$",
    r"\.private$",
    r"^localhost$",
]


@dataclass
class FallbackEvent:
    """降级事件记录"""
    timestamp: datetime
    error_reason: str
    fallback_duration_ms: Optional[float] = None


@dataclass
class OCRConfig:
    """OCR 服务配置"""
    preferred_mode: OCRMode = OCRMode.AUTO
    cloud_url: str = "http://192.168.1.100:8868/ocr"
    cloud_timeout: int = 30   # seconds
    local_timeout: int = 60   # seconds
    retry_count: int = 1
    local_lang: str = "ch"
    local_use_angle_cls: bool = True
    local_use_gpu: bool = False
    local_model_dir: Optional[str] = None



class OCRService:
    """
    统一双模式 OCR 服务。

    行为:
    1. 始终先尝试 preferred_mode（通常为云端）
    2. 云端超时/错误 → 自动降级到本地，记录降级事件
    3. 下次调用 → 自动尝试恢复云端（无熔断状态）
    4. 两者均失败 → 抛出 OCRUnavailableError
    5. 跟踪降级状态：记录降级开始时间，云端恢复时计算并补录持续时长
    """

    def __init__(self, config: OCRConfig):
        self._config = config
        # Validate intranet URL at startup
        if not self._validate_intranet_url(config.cloud_url):
            raise ValueError(
                f"云端 OCR 地址必须为内网地址，当前配置: {config.cloud_url}"
            )
        # Fallback tracking state
        self._fallback_start_time: Optional[float] = None
        self._fallback_events: list[FallbackEvent] = []
        self._paddle_engine = None

    @property
    def config(self) -> OCRConfig:
        return self._config

    @property
    def fallback_events(self) -> list[FallbackEvent]:
        return list(self._fallback_events)

    @property
    def is_in_fallback(self) -> bool:
        return self._fallback_start_time is not None

    async def recognize(self, image_bytes: bytes, filename: str) -> OCRResult:
        """
        识别图片中的文字。

        根据 preferred_mode 分发到三条路由路径：
        - AUTO: 先云端后本地，保留降级事件记录
        - LOCAL: 仅本地，失败抛 OCRUnavailableError
        - REMOTE / CLOUD_VL: 仅云端，失败抛 OCRUnavailableError
        """
        start_time = time.monotonic()
        mode = self._config.preferred_mode

        if mode in (OCRMode.REMOTE, OCRMode.CLOUD_VL):
            return await self._run_remote_only(image_bytes, filename, start_time)
        elif mode == OCRMode.LOCAL:
            return await self._run_local_only(image_bytes, filename, start_time)
        else:  # AUTO
            return await self._run_auto(image_bytes, filename, start_time)


    async def _run_remote_only(
        self, image_bytes: bytes, filename: str, start_time: float
    ) -> OCRResult:
        """仅云端模式，失败抛 OCRUnavailableError，不记录降级事件。"""
        for attempt in range(self._config.retry_count + 1):
            try:
                raw_text = await self._call_cloud(image_bytes, filename)
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return OCRResult(
                    raw_text=raw_text,
                    mode_used=OCRMode.REMOTE,
                    elapsed_ms=elapsed_ms,
                    char_count=len(raw_text),
                )
            except Exception as e:
                if attempt < self._config.retry_count:
                    logger.warning(
                        "云端 OCR 第 %d 次尝试失败: %s，重试中...",
                        attempt + 1,
                        str(e),
                    )
        raise OCRUnavailableError()

    async def _run_local_only(
        self, image_bytes: bytes, filename: str, start_time: float
    ) -> OCRResult:
        """仅本地模式，失败抛 OCRUnavailableError，不记录降级事件。"""
        try:
            raw_text = await self._call_local(image_bytes, filename)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return OCRResult(
                raw_text=raw_text,
                mode_used=OCRMode.LOCAL,
                elapsed_ms=elapsed_ms,
                char_count=len(raw_text),
            )
        except Exception as e:
            logger.error("本地 OCR 不可用: %s", str(e))
            raise OCRUnavailableError() from e

    async def _run_auto(
        self, image_bytes: bytes, filename: str, start_time: float
    ) -> OCRResult:
        """AUTO 模式：先云端后本地，保留降级事件记录逻辑。"""
        cloud_error = None

        # Try cloud with retries
        for attempt in range(self._config.retry_count + 1):
            try:
                raw_text = await self._call_cloud(image_bytes, filename)
                elapsed_ms = int((time.monotonic() - start_time) * 1000)

                # Cloud succeeded - check if we were in fallback and log recovery
                if self._fallback_start_time is not None:
                    recovery_duration_ms = (time.monotonic() - self._fallback_start_time) * 1000
                    logger.info(
                        "云端 OCR 恢复可用，降级持续时长: %.0f ms",
                        recovery_duration_ms,
                    )
                    if self._fallback_events:
                        self._fallback_events[-1].fallback_duration_ms = recovery_duration_ms
                    self._fallback_start_time = None

                return OCRResult(
                    raw_text=raw_text,
                    mode_used=OCRMode.REMOTE,
                    elapsed_ms=elapsed_ms,
                    char_count=len(raw_text),
                )
            except Exception as e:
                cloud_error = e
                if attempt < self._config.retry_count:
                    logger.warning(
                        "云端 OCR 第 %d 次尝试失败: %s，重试中...",
                        attempt + 1,
                        str(e),
                    )

        # Cloud failed - record fallback event and try local
        error_reason = str(cloud_error)
        now = datetime.now()

        if self._fallback_start_time is None:
            self._fallback_start_time = time.monotonic()

        fallback_event = FallbackEvent(timestamp=now, error_reason=error_reason)
        self._fallback_events.append(fallback_event)

        logger.warning(
            "云端 OCR 不可用 (原因: %s)，降级到本地模式 [%s]",
            error_reason,
            now.isoformat(),
        )

        # Try local
        try:
            raw_text = await self._call_local(image_bytes, filename)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return OCRResult(
                raw_text=raw_text,
                mode_used=OCRMode.LOCAL,
                elapsed_ms=elapsed_ms,
                char_count=len(raw_text),
            )
        except Exception as local_error:
            logger.error(
                "本地 OCR 也不可用: %s，OCR 服务完全不可用",
                str(local_error),
            )
            raise OCRUnavailableError() from local_error

    async def _call_cloud(self, image_bytes: bytes, filename: str) -> str:
        """
        调用云端 PaddleOCR-VL API（multipart file 上传）。
        """
        import asyncio
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self._config.cloud_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                image_bytes,
                filename=filename,
                content_type="image/png",
            )
            async with session.post(
                self._config.cloud_url,
                data=form,
            ) as resp:
                resp.raise_for_status()
                result = await resp.json()
                return result.get("text", "")

    async def _call_local(self, image_bytes: bytes, filename: str) -> str:
        """
        调用本地 PaddleOCR 模型进行推理。

        流程: 入口校验 → 懒加载引擎 → 图像解码 → 线程池推理 → 超时控制 → 结果拼接
        """
        # 1. 输入校验
        if not image_bytes:
            raise ValueError("图像数据为空")

        # 2. 懒加载 PaddleOCR
        if self._paddle_engine is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError:
                raise RuntimeError(
                    "PaddleOCR 未安装，请执行: pip install 'paddleocr>=2.7,<3' 'paddlepaddle>=2.6,<3'"
                )
            init_kwargs = {
                "lang": self._config.local_lang,
                "use_angle_cls": self._config.local_use_angle_cls,
                "use_gpu": self._config.local_use_gpu,
                "show_log": False,
            }
            if self._config.local_model_dir:
                init_kwargs["det_model_dir"] = self._config.local_model_dir
                init_kwargs["rec_model_dir"] = self._config.local_model_dir
                init_kwargs["cls_model_dir"] = self._config.local_model_dir
            self._paddle_engine = PaddleOCR(**init_kwargs)

        # 3. 图像解码
        import numpy as np
        import cv2
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("图像解码失败，请检查文件格式")

        # 大图缩放，避免超出 PaddleOCR 的 max_side_limit
        max_side = 4000
        h, w = img.shape[:2]
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))

        # 4. 线程池推理 + 超时控制
        import asyncio
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, self._paddle_engine.ocr, img, True)
        result = await asyncio.wait_for(future, timeout=self._config.local_timeout)

        # 5. 结果拼接
        if not result or not result[0]:
            return ""
        lines = [line[1][0] for line in result[0] if line[1]]
        return "\n".join(lines)


    def _validate_intranet_url(self, url: str) -> bool:
        """
        校验 URL 是否为内网地址。

        检查规则:
        - 私有 IP 段: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8
        - 内网域名: *.local, *.internal, *.intranet, *.corp, *.lan, *.private, localhost
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False

            # Try to parse as IP address
            try:
                addr = ip_address(hostname)
                return any(addr in network for network in _PRIVATE_NETWORKS)
            except ValueError:
                pass

            # Check against intranet domain patterns
            hostname_lower = hostname.lower()
            for pattern in _INTRANET_DOMAIN_PATTERNS:
                if re.search(pattern, hostname_lower):
                    return True

            return False
        except Exception:
            return False
