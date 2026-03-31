# 实施计划：本地 PaddleOCR 回退

## 概述

基于设计文档，将 OCRService 的 `_call_local` 存根替换为完整的本地 PaddleOCR 推理实现。按增量步骤推进：先扩展数据模型和配置，再实现核心推理逻辑，最后重写路由并集成所有组件。每个步骤构建在前一步之上，确保无孤立代码。

## Tasks

- [x] 1. 扩展 OCRMode 枚举与配置模型
  - [x] 1.1 在 `agent_core/models.py` 中为 `OCRMode` 枚举新增 `AUTO = "auto"` 和 `REMOTE = "remote"` 两个值，保留 `CLOUD_VL = "cloud_vl"` 不变
    - _需求: 7.1_
  - [x] 1.2 在 `agent_core/config.py` 中为应用层 `OCRConfig`（Pydantic）新增四个字段：`local_lang: str = "ch"`、`local_use_angle_cls: bool = True`、`local_use_gpu: bool = False`、`local_model_dir: Optional[str] = None`；将 `preferred_mode` 默认值从 `"cloud_vl"` 改为 `"auto"`；为 `preferred_mode` 添加 Pydantic `@field_validator`，将输入值转为小写后再赋值（实现大小写不敏感解析，如 `"AUTO"` → `"auto"`、`"Cloud_VL"` → `"cloud_vl"`）
    - _需求: 1.1, 7.2, 7.8_
  - [x] 1.3 在 `tools/ocr_service.py` 中为服务层 `OCRConfig`（dataclass）新增同样的四个字段，默认值与应用层一致；将 `preferred_mode` 默认值从 `OCRMode.CLOUD_VL` 改为 `OCRMode.AUTO`
    - _需求: 1.1, 7.2_
  - [x] 1.4 编写属性测试：属性 1 — 配置字段默认值一致性
    - **属性 1: 配置字段保持与默认值一致**
    - 生成随机 lang/bool/path 值，构造两种 OCRConfig 并验证字段默认值和显式赋值
    - **验证需求: 1.1**

- [x] 2. 连接应用层配置到服务层
  - [x] 2.1 修改 `agent_core/core.py` 中 `AgentCore.__init__`，在构造 `OCRServiceConfig` 时传递新增的四个字段（`local_lang`、`local_use_angle_cls`、`local_use_gpu`、`local_model_dir`）
    - _需求: 1.2_
  - [x] 2.2 编写属性测试：属性 2 — 应用层到服务层配置传递
    - **属性 2: 应用层到服务层配置传递**
    - 生成随机配置值，通过应用层传递到服务层并比较每个字段值
    - **验证需求: 1.2**

- [x] 3. 检查点 — 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 4. 实现 `_call_local` 核心推理逻辑
  - [x] 4.1 在 `tools/ocr_service.py` 的 `OCRService.__init__` 中新增 `self._paddle_engine = None` 私有属性；实现 `_call_local` 方法：入口校验空字节 → 延迟导入 `paddleocr` → 懒加载 PaddleOCR 引擎 → `numpy` + `cv2.imdecode` 解码图像 → 校验解码结果 → `run_in_executor` 线程池推理 → `asyncio.wait_for` 超时控制 → 拼接识别文本行返回
    - 空字节抛出 `ValueError("图像数据为空")`
    - `paddleocr` 导入失败抛出 `RuntimeError`，提示安装命令
    - `cv2.imdecode` 返回 None 时抛出 `ValueError("图像解码失败，请检查文件格式")`
    - PaddleOCR 返回空结果或 None 时返回空字符串
    - 超时由 `asyncio.wait_for(future, timeout=self._config.local_timeout)` 控制
    - _需求: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 5.1, 5.2, 5.3, 8.1, 8.2, 8.3_
  - [x] 4.2 编写属性测试：属性 3 — PaddleOCR 结果文本行拼接
    - **属性 3: PaddleOCR 结果文本行拼接**
    - 生成随机文字行列表，mock PaddleOCR 返回值，验证输出等于 `"\n".join(lines)`
    - **验证需求: 3.3**
  - [x] 4.3 编写属性测试：属性 4 — 非法图像字节触发 ValueError
    - **属性 4: 非法图像字节触发 ValueError**
    - 生成随机非图像字节（过滤合法图像头），调用 `_call_local` 验证抛出 ValueError 且消息包含"图像解码失败"
    - **验证需求: 5.2**
  - [x] 4.4 编写属性测试：属性 7 — 本地推理超时强制执行
    - **属性 7: 本地推理超时强制执行**
    - 生成随机超时值（0.01-0.5s），mock 慢推理，验证抛出 `asyncio.TimeoutError`
    - 实现方式：mock `_paddle_engine.ocr` 为一个内部调用 `time.sleep(超时值 * 2)` 的函数来模拟慢推理，`asyncio.wait_for` 会在超时后抛出 `TimeoutError`；注意底层线程会继续运行直到 sleep 结束，但测试只需验证调用方收到 `TimeoutError` 即可
    - **验证需求: 8.1, 8.2**
  - [x] 4.5 编写单元测试：`_call_local` 边界情况
    - 测试空字节抛出 `ValueError("图像数据为空")`
    - 测试 PaddleOCR 未安装时抛出 `RuntimeError`
    - 测试懒加载：构造后 `_paddle_engine` 为 None，首次调用后非 None，多次调用复用同一实例
    - 测试 PaddleOCR 返回 None / 空列表时返回空字符串
    - 测试 PaddleOCR 未安装时云端模式正常工作
    - _需求: 2.1, 2.2, 2.3, 2.4, 3.4, 4.1, 4.2, 5.1_

- [x] 5. 检查点 — 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 6. 重写 `recognize()` 路由逻辑与三模式支持
  - [x] 6.1 在 `tools/ocr_service.py` 中重写 `recognize()` 方法，根据 `preferred_mode` 分发到三条路由路径：`_run_auto`（AUTO）、`_run_local_only`（LOCAL）、`_run_remote_only`（REMOTE / CLOUD_VL）
    - `_run_remote_only`：仅云端，失败抛 `OCRUnavailableError`，不记录降级事件
    - `_run_local_only`：仅本地，失败抛 `OCRUnavailableError`，不记录降级事件
    - `_run_auto`：先云端后本地，保留降级事件记录逻辑（`_fallback_events`、`_fallback_start_time`），双失败抛 `OCRUnavailableError`
    - 云端成功时 `mode_used` 统一设为 `OCRMode.REMOTE`（不再使用 `CLOUD_VL`）
    - 本地成功时 `mode_used` 设为 `OCRMode.LOCAL`
    - 移除旧的 `_try_cloud_then_local` 和 `_try_local_then_cloud` 方法（已被三条新路由路径替代），移除前需确认无其他代码引用这两个方法
    - _需求: 7.3, 7.4, 7.5, 7.6, 7.7, 7.9_
  - [x] 6.2 同步更新现有测试中的 `OCRMode.CLOUD_VL` 引用：检查并更新 `tests/test_ocr_service.py` 及其他测试文件中所有将 `mode_used` 与 `OCRMode.CLOUD_VL` 比较的断言，改为 `OCRMode.REMOTE`；确保现有测试适配新的三模式路由（此步骤必须在检查点之前完成，否则路由重写后现有测试会因 mode_used 变更而失败）
    - _需求: 7.1, 7.9_
  - [x] 6.3 编写属性测试：属性 5 — 单模式路由隔离
    - **属性 5: 单模式路由隔离**
    - 生成随机模式（LOCAL/REMOTE/CLOUD_VL），mock 两个后端，验证仅调用对应后端
    - **验证需求: 7.4, 7.5**
  - [x] 6.4 编写属性测试：属性 6 — AUTO 模式云端失败自动降级
    - **属性 6: AUTO 模式云端失败自动降级**
    - mock 云端失败 + 本地成功，验证返回 `mode_used == LOCAL` 的 OCRResult
    - **验证需求: 7.3**
  - [x] 6.5 编写单元测试：路由与模式切换边界情况
    - 测试 LOCAL 模式 + PaddleOCR 未安装 → `OCRUnavailableError`
    - 测试 REMOTE 模式 + 云端不可用 → `OCRUnavailableError`
    - 测试 OCRMode 枚举包含 AUTO、LOCAL、REMOTE、CLOUD_VL 四个值
    - 测试 `preferred_mode` 默认值为 `"auto"`
    - _需求: 7.1, 7.2, 7.6, 7.7_

- [x] 7. 检查点 — 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 8. 更新依赖声明与配置文件
  - [x] 8.1 更新 `requirements.txt`：添加 `numpy` 和 `opencv-python-headless` 作为正式依赖；以注释形式添加 `paddleocr>=2.7.0` 和 `paddlepaddle>=2.6.0` 作为可选依赖
    - _需求: 6.1, 6.2, 6.3_
  - [x] 8.2 更新 `config.yaml`：将 `preferred_mode` 改为 `auto`，新增 `local_lang`、`local_use_angle_cls`、`local_use_gpu`、`local_model_dir`（注释形式）配置项示例
    - _需求: 1.3, 7.8_
  - [x] 8.3 编写单元测试：验证 `config.yaml` 接受 auto/local/remote/cloud_vl 四种值（含大小写变体如 `"AUTO"`、`"Remote"`）
    - _需求: 7.8_

- [x] 9. 最终检查点 — 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

## 备注

- 标记 `*` 的子任务为可选测试任务，可跳过以加速 MVP 交付
- 每个任务引用了具体的需求编号，确保可追溯性
- 属性测试验证跨所有输入的通用正确性属性，单元测试验证具体示例和边界情况
- 检查点确保增量验证，避免问题累积
