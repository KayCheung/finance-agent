# 需求文档

## 简介

本文档定义了 OCRService 本地 PaddleOCR 推理回退功能的需求。当前系统的 `_call_local` 方法为存根实现（抛出 `NotImplementedError`），需要将其替换为基于 PaddleOCR Python 库的本地推理能力，使得云端 OCR 不可用时系统能自动降级到本地模型完成文字识别。

## 术语表

- **OCR_Service**: 统一双模式 OCR 服务，位于 `tools/ocr_service.py`，负责图片文字识别
- **PaddleOCR_Engine**: PaddleOCR Python 库提供的本地 OCR 推理引擎实例
- **OCR_Config（应用层）**: 应用配置模型，位于 `agent_core/config.py`（Pydantic BaseModel），从 `config.yaml` 加载配置并传递给 OCR_Service
- **OCR_Config（服务层）**: OCR 服务内部配置，位于 `tools/ocr_service.py`（dataclass），由 OCR_Service 直接使用
- **Local_Model**: 本地 PaddleOCR 模型文件及其运行时实例
- **Lazy_Loading**: 延迟加载策略，仅在首次调用本地推理时初始化模型，避免启动开销
- **Image_Bytes**: 待识别图片的二进制数据（bytes 类型）
- **OCR_Result**: OCR 识别结果数据模型，包含识别文本、使用模式、耗时等元数据

## 需求

### 需求 1：本地 PaddleOCR 配置

**用户故事：** 作为系统管理员，我希望能在应用配置中设置本地 PaddleOCR 模型参数，以便无需修改代码即可控制本地 OCR 引擎的行为。

#### 验收标准

1. `agent_core/config.py` 中的 OCR_Config（Pydantic）和 `tools/ocr_service.py` 中的 OCR_Config（dataclass）均应新增以下字段：`local_lang`（默认 `"ch"`）、`local_use_angle_cls`（默认 `true`）、`local_use_gpu`（默认 `false`）、`local_model_dir`（默认 `null`）
2. `agent_core/core.py` 中 `AgentCore.__init__` 在构造 `OCRServiceConfig` 时，应将新增的四个字段从应用层 OCR_Config 传递到服务层 OCR_Config
3. 当 `config.yaml` 中包含 `ocr.local_lang`、`ocr.local_use_angle_cls`、`ocr.local_use_gpu` 或 `ocr.local_model_dir` 配置项时，应用层 OCR_Config 应正确加载这些值

### 需求 2：模型懒加载

**用户故事：** 作为开发者，我希望 PaddleOCR 模型仅在首次需要时才加载，以避免在不使用本地 OCR 时影响应用启动速度。

#### 验收标准

1. OCR_Service 应将 PaddleOCR_Engine 的初始化推迟到首次调用 `_call_local` 时
2. 当 `_call_local` 首次被调用时，OCR_Service 应使用 OCR_Config 中的参数初始化 PaddleOCR_Engine
3. 当 `_call_local` 在 PaddleOCR_Engine 已初始化后被调用时，OCR_Service 应复用已有的 PaddleOCR_Engine 实例，不重新初始化
4. OCR_Service 应将 PaddleOCR_Engine 实例存储为私有属性，以便跨调用复用

### 需求 3：本地 OCR 推理

**用户故事：** 作为用户，我希望系统能使用本地 PaddleOCR 模型进行 OCR 识别，以便在云端服务不可用时仍能完成文字识别。

#### 验收标准

1. 当 `_call_local` 接收到有效的 Image_Bytes 时，OCR_Service 应先进行输入校验（见需求 5），然后使用 `numpy` + `cv2.imdecode` 将 Image_Bytes 解码为图像数组
2. 当图像解码成功时，OCR_Service 应将图像数组传递给 PaddleOCR_Engine 进行文字识别
3. 当 PaddleOCR_Engine 返回识别结果时，OCR_Service 应将所有识别到的文字行用换行符拼接为单个字符串
4. 当 PaddleOCR_Engine 返回空结果或 `None` 时，OCR_Service 应返回空字符串
5. OCR_Service 应在线程池执行器（`asyncio.get_event_loop().run_in_executor`）中运行 PaddleOCR 推理，以避免阻塞异步事件循环

### 需求 4：PaddleOCR 依赖缺失时的优雅处理

**用户故事：** 作为开发者，我希望系统在未安装 PaddleOCR 库时能优雅处理，以便应用仍能正常启动并使用云端 OCR。

#### 验收标准

1. `paddleocr` 的导入应在 `_call_local` 内部延迟执行（而非模块顶层），若导入失败则抛出描述性的 `RuntimeError`，提示需要安装 PaddleOCR（如 `pip install paddleocr paddlepaddle`）
2. 若 `paddleocr` 未安装，应用启动和云端 OCR 模式均不受影响

### 需求 5：图像解码错误处理

**用户故事：** 作为开发者，我希望图像解码错误能被正确处理，以便损坏或无效的图片产生清晰的错误信息，而非难以理解的异常。

#### 验收标准

1. `_call_local` 入口处应首先检查 Image_Bytes 是否为空（长度为零），若为空则抛出 `ValueError("图像数据为空")`
2. 若 Image_Bytes 非空但 `cv2.imdecode` 返回 `None`（无法解码为有效图像），则抛出 `ValueError("图像解码失败，请检查文件格式")`
3. 输入校验（AC1、AC2）应在 PaddleOCR 推理之前执行

### 需求 6：PaddleOCR 依赖声明

**用户故事：** 作为开发者，我希望 PaddleOCR 和 PaddlePaddle 依赖在项目中声明，以便在需要时可以安装本地 OCR 功能。

#### 验收标准

1. `requirements.txt` 应将 `paddleocr>=2.7.0` 作为可选依赖包含（以注释标注为可选）
2. `requirements.txt` 应将 `paddlepaddle>=2.6.0` 作为可选依赖包含（以注释标注为可选）
3. `requirements.txt` 应包含 `numpy` 和 `opencv-python-headless` 依赖（PaddleOCR 运行时必需）

### 需求 7：OCR 模式开关

**用户故事：** 作为系统管理员，我希望能通过配置选择 OCR 运行模式（AUTO / LOCAL / REMOTE），以便根据部署环境灵活控制 OCR 的调用策略。

#### 验收标准

1. `OCRMode` 枚举应新增 `AUTO = "auto"` 和 `REMOTE = "remote"` 两个值，同时保留 `CLOUD_VL = "cloud_vl"` 作为 `REMOTE` 的向后兼容别名，`LOCAL = "local"` 保持不变
2. OCR_Config 的 `preferred_mode` 字段默认值应改为 `"auto"`
3. 当 `preferred_mode` 为 `AUTO` 时，OCR_Service 应先尝试云端（REMOTE），云端失败后自动降级到本地（LOCAL）；这是一条全新的路由路径，不复用现有的 `_try_cloud_then_local`（因为现有方法在本地也失败时抛出 `OCRUnavailableError`，AUTO 模式行为与此一致但路由入口不同）
4. 当 `preferred_mode` 为 `LOCAL` 时，OCR_Service 应仅使用本地 PaddleOCR 模型进行推理，云端完全不参与；若本地失败则直接抛出 `OCRUnavailableError`，不降级到云端
5. 当 `preferred_mode` 为 `REMOTE` 时，OCR_Service 应仅使用云端 PaddleOCR-VL API 进行推理，本地完全不参与；若云端失败则直接抛出 `OCRUnavailableError`，不降级到本地
6. 当 `preferred_mode` 为 `LOCAL` 且 PaddleOCR 未安装时，OCR_Service 应抛出 `OCRUnavailableError`
7. 当 `preferred_mode` 为 `REMOTE` 且云端不可用时，OCR_Service 应抛出 `OCRUnavailableError`
8. 配置文件中 `ocr.preferred_mode` 应接受 `"auto"`、`"local"`、`"remote"` 三个字符串值（不区分大小写），同时继续兼容旧值 `"cloud_vl"`（等价于 `"remote"`）
9. `recognize()` 方法的路由逻辑应根据三个模式值重写：`AUTO` → 先云端后本地（双降级）；`LOCAL` → 仅本地（单模式）；`REMOTE` → 仅云端（单模式）；`CLOUD_VL` → 等价于 `REMOTE`

### 需求 8：本地推理超时控制

**用户故事：** 作为系统管理员，我希望本地 OCR 推理遵守配置的超时时间，以避免模型推理过慢时无限期阻塞系统。

#### 验收标准

1. 在本地 OCR 推理运行期间，OCR_Service 应将 OCR_Config 中的 `local_timeout` 值作为最大执行时间
2. 若本地 OCR 推理超过 `local_timeout` 时长，OCR_Service 应通过 `asyncio.wait_for` 取消等待并抛出 `TimeoutError`
3. 由于 Python 线程池中的任务无法被强制终止，超时后底层 PaddleOCR 推理线程可能仍在运行直到自然完成；OCR_Service 不保证线程立即释放，但应确保超时后立即向调用方返回错误，不阻塞后续请求
