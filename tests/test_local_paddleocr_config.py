"""
tests/test_local_paddleocr_config.py
属性测试 — 本地 PaddleOCR 配置字段

Feature: local-paddleocr-fallback
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_core.config import OCRConfig as AppOCRConfig
from tools.ocr_service import OCRConfig as ServiceOCRConfig
from agent_core.models import OCRMode


class TestProperty1ConfigFieldDefaultValueConsistency:
    """
    Feature: local-paddleocr-fallback, Property 1: 配置字段保持与默认值一致

    **Validates: Requirements 1.1**

    对于任意 OCRConfig 实例（Pydantic 和 dataclass 版本），
    当未显式提供 local_lang、local_use_angle_cls、local_use_gpu、local_model_dir 时，
    这些字段应分别为 "ch"、True、False、None；
    当显式提供任意合法值时，字段应保持提供的值不变。
    """

    # ── Default values ──

    def test_app_ocr_config_defaults(self):
        """Pydantic OCRConfig defaults are correct when no values provided."""
        cfg = AppOCRConfig()
        assert cfg.local_lang == "ch"
        assert cfg.local_use_angle_cls is True
        assert cfg.local_use_gpu is False
        assert cfg.local_model_dir is None

    def test_service_ocr_config_defaults(self):
        """Dataclass OCRConfig defaults are correct when no values provided."""
        cfg = ServiceOCRConfig()
        assert cfg.local_lang == "ch"
        assert cfg.local_use_angle_cls is True
        assert cfg.local_use_gpu is False
        assert cfg.local_model_dir is None

    # ── Property: explicit values retained (Pydantic) ──

    @given(
        lang=st.text(min_size=1, max_size=10),
        use_angle_cls=st.booleans(),
        use_gpu=st.booleans(),
        model_dir=st.none() | st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_app_ocr_config_retains_explicit_values(
        self, lang: str, use_angle_cls: bool, use_gpu: bool, model_dir
    ):
        """Pydantic OCRConfig retains any explicitly provided legal values."""
        cfg = AppOCRConfig(
            local_lang=lang,
            local_use_angle_cls=use_angle_cls,
            local_use_gpu=use_gpu,
            local_model_dir=model_dir,
        )
        assert cfg.local_lang == lang
        assert cfg.local_use_angle_cls == use_angle_cls
        assert cfg.local_use_gpu == use_gpu
        assert cfg.local_model_dir == model_dir

    # ── Property: explicit values retained (dataclass) ──

    @given(
        lang=st.text(min_size=1, max_size=10),
        use_angle_cls=st.booleans(),
        use_gpu=st.booleans(),
        model_dir=st.none() | st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_service_ocr_config_retains_explicit_values(
        self, lang: str, use_angle_cls: bool, use_gpu: bool, model_dir
    ):
        """Dataclass OCRConfig retains any explicitly provided legal values."""
        cfg = ServiceOCRConfig(
            local_lang=lang,
            local_use_angle_cls=use_angle_cls,
            local_use_gpu=use_gpu,
            local_model_dir=model_dir,
        )
        assert cfg.local_lang == lang
        assert cfg.local_use_angle_cls == use_angle_cls
        assert cfg.local_use_gpu == use_gpu
        assert cfg.local_model_dir == model_dir


class TestProperty2AppLayerToServiceLayerConfigPropagation:
    """
    Feature: local-paddleocr-fallback, Property 2: 应用层到服务层配置传递

    **Validates: Requirements 1.2**

    对于任意一组合法的 OCR 配置值（包括 local_lang、local_use_angle_cls、
    local_use_gpu、local_model_dir），通过应用层 OCRConfig 构造并传递到
    服务层 OCRConfig 后，服务层实例中的每个字段值应与应用层提供的值完全一致。
    """

    @given(
        lang=st.text(min_size=1, max_size=10),
        use_angle_cls=st.booleans(),
        use_gpu=st.booleans(),
        model_dir=st.none() | st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_config_propagation_preserves_all_fields(
        self, lang: str, use_angle_cls: bool, use_gpu: bool, model_dir
    ):
        """
        Simulates what AgentCore.__init__ does: constructs an AppOCRConfig,
        then passes its field values to a ServiceOCRConfig. All four local
        config fields must match exactly between the two layers.
        """
        # 1. Construct application-layer config with random values
        app_cfg = AppOCRConfig(
            local_lang=lang,
            local_use_angle_cls=use_angle_cls,
            local_use_gpu=use_gpu,
            local_model_dir=model_dir,
        )

        # 2. Propagate to service-layer config (mirrors AgentCore.__init__)
        svc_cfg = ServiceOCRConfig(
            preferred_mode=OCRMode(app_cfg.preferred_mode),
            cloud_url=app_cfg.cloud_url,
            cloud_timeout=app_cfg.cloud_timeout,
            local_timeout=app_cfg.local_timeout,
            retry_count=app_cfg.retry_count,
            local_lang=app_cfg.local_lang,
            local_use_angle_cls=app_cfg.local_use_angle_cls,
            local_use_gpu=app_cfg.local_use_gpu,
            local_model_dir=app_cfg.local_model_dir,
        )

        # 3. Verify all four local config fields match
        assert svc_cfg.local_lang == app_cfg.local_lang
        assert svc_cfg.local_use_angle_cls == app_cfg.local_use_angle_cls
        assert svc_cfg.local_use_gpu == app_cfg.local_use_gpu
        assert svc_cfg.local_model_dir == app_cfg.local_model_dir

        # Also verify the shared fields propagated correctly
        assert svc_cfg.preferred_mode == OCRMode(app_cfg.preferred_mode)
        assert svc_cfg.cloud_url == app_cfg.cloud_url
        assert svc_cfg.cloud_timeout == app_cfg.cloud_timeout
        assert svc_cfg.local_timeout == app_cfg.local_timeout
        assert svc_cfg.retry_count == app_cfg.retry_count


class TestConfigYamlModeValues:
    """
    单元测试：config.yaml 接受 auto/local/remote/cloud_vl 四种值

    **Validates: Requirements 7.8**
    """

    @pytest.mark.parametrize("mode_value,expected", [
        ("auto", "auto"),
        ("local", "local"),
        ("remote", "remote"),
        ("cloud_vl", "cloud_vl"),
        ("AUTO", "auto"),
        ("Local", "local"),
        ("Remote", "remote"),
        ("Cloud_VL", "cloud_vl"),
        ("AUTO", "auto"),
        ("LOCAL", "local"),
        ("REMOTE", "remote"),
        ("CLOUD_VL", "cloud_vl"),
    ])
    def test_preferred_mode_accepts_value(self, mode_value, expected):
        cfg = AppOCRConfig(preferred_mode=mode_value)
        assert cfg.preferred_mode == expected
