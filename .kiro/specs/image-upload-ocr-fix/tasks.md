# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - 图片上传 base64 直拼 prompt 及工具注册不完整
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the four defects exist
  - **Scoped PBT Approach**: Scope the property to concrete failing cases for each defect
  - Test 1a: 构造包含图片的 `AgentRequest`（含 base64 数据），Mock Agent SDK，调用 `_process_request`，断言构建的 prompt 中不包含完整 base64 字符串（isBugCondition: `request.images IS NOT EMPTY AND base64DataInPrompt(request)`）
  - Test 1b: Mock `OCRService.recognize`，验证上传图片时该方法被调用（isBugCondition: `ocrServiceNotCalled(input)`）
  - Test 1c: 验证 `ocr_invoice` 工具内部不使用 `requests.post`，而是委托 `OCRService.recognize()`
  - Test 1d: 验证 `_create_sdk_client` 的 `allowed_tools` 不包含 `mcp__finance-tools__tax_calculate`（在未修复代码上应通过，确认缺陷存在）
  - Test 1e: 验证 `get_sdk_tools()` 返回列表不包含名为 `tax_calculate` 的工具函数（在未修复代码上应通过，确认缺陷存在）
  - Run test on UNFIXED code - expect FAILURE (this confirms the bug exists)
  - **EXPECTED OUTCOME**: Test FAILS - prompt 包含 base64 数据、OCRService 未被调用、ocr_invoice 直接调用 requests.post、allowed_tools 缺少 tax_calculate、get_sdk_tools 缺少 tax_calculate
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 非图片请求及已有工具行为不变
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: 纯文字消息（无图片）经 `_process_request` 处理后，prompt 仅包含用户文字，Agent 正常返回回复
  - Observe: 空消息且无图片时，返回 "请输入您的问题或上传发票图片。"
  - Observe: AI 回复包含 `%%VOUCHER_JSON_START%%...%%VOUCHER_JSON_END%%` 时，凭证 JSON 正确解析为 dict
  - Observe: Agent SDK 抛出异常时，返回 `success=False` 的 `AgentResponse` 且 `errors` 非空
  - Observe: `classify_account` 和 `generate_mcp_voucher` 的函数签名（参数名、返回格式）保持不变
  - Write property-based test: for all non-image AgentRequest（`images` 为空），`_process_request` 的 prompt 构建逻辑与修复前一致（from Preservation Requirements in design: Property 4）
  - Write property-based test: for all `classify_account` / `generate_mcp_voucher` 调用，工具签名和返回格式不变（from Preservation Requirements in design: Property 5）
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix for 图片上传 OCR 未调用及工具注册不完整

  - [x] 3.1 Implement OCRService integration in `_process_request` (core.py)
    - 注意：`AgentConfig` 目前只有 `model` 和 `max_turns` 字段，OCR 配置在 `config.yaml` 的 `ocr:` 节下，由 `AppConfig.ocr` 承载。`AgentCore.__init__` 应新增 `ocr_config: Optional[OCRConfig] = None` 参数，由 `main.py` 中的 `_get_agent_core()` 从 `_config.ocr` 传入。若未传入则使用 `OCRConfig()` 默认值。
    - 在 `AgentCore.__init__` 中基于 `ocr_config` 创建 `OCRService` 实例
    - 调用 `_tools.set_ocr_service(self._ocr_service)` 注入实例到 `_tools.py`
    - 将 `_process_request` 中直接拼接 base64 的逻辑（第 270-278 行）替换为：对每张图片调用 `self._ocr_service.recognize(image_bytes, filename)`，将 `OCRResult.raw_text` 放入 prompt
    - 使用明确标记格式 `"以下是 OCR 识别结果：\n{ocr_text}"` 构建 prompt
    - 在调用 OCR 前将 `image_base64` 字符串通过 `base64.b64decode` 解码为 `bytes`
    - 捕获 `OCRUnavailableError`，返回友好错误提示 `AgentResponse(success=False, reply="OCR 服务暂时不可用...")`
    - 记录 OCR 执行日志（模式、耗时、字符数）
    - _Bug_Condition: isBugCondition(input) where input.images IS NOT EMPTY AND (base64DataInPrompt OR ocrServiceNotCalled)_
    - _Expected_Behavior: prompt DOES NOT CONTAIN base64 data AND prompt CONTAINS ocr_text AND OCRService.recognize WAS CALLED_
    - _Preservation: 纯文字消息、空消息、凭证解析、异常处理逻辑不受影响_
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.2 Refactor `ocr_invoice` tool to delegate to OCRService (_tools.py)
    - 添加模块级变量 `_ocr_service: Optional[OCRService] = None`
    - 添加 `set_ocr_service(instance: OCRService) -> None` 函数
    - 移除 `ocr_invoice` 中的 `requests.post` 直接调用逻辑
    - 改为通过 `_ocr_service.recognize(img_bytes, filename)` 执行 OCR
    - 当 `_ocr_service is None` 时返回 `{"error": "OCR 服务未初始化，请检查系统配置"}` 而非抛出 `AttributeError`
    - 移除 `requests`、`REMOTE_OCR_URL`、`REMOTE_OCR_TOKEN` 等冗余导入和变量
    - _Bug_Condition: ocr_invoice 直接使用 requests.post 绕过 OCRService_
    - _Expected_Behavior: OCRService.recognize WAS CALLED AND requests.post WAS NOT CALLED_
    - _Preservation: ocr_invoice 工具签名和返回格式不变_
    - _Requirements: 2.5_

  - [x] 3.3 Add `tax_calculate` tool and update registrations (_tools.py + core.py)
    - 在 `_tools.py` 中新增 `tax_calculate` @tool 函数，调用 `tools.tax_calculator.calculate_tax`
    - 函数内部进行类型转换：`Decimal(str(total_amount))` 和 `Decimal(str(tax_rate))`
    - 更新 `get_sdk_tools()` 返回列表加入 `tax_calculate`
    - 在 `_create_sdk_client` 的 `allowed_tools` 列表中添加 `"mcp__finance-tools__tax_calculate"`
    - _Bug_Condition: "tax_calculate" NOT IN allowed_tools AND "tax_calculate" NOT IN get_sdk_tools()_
    - _Expected_Behavior: "mcp__finance-tools__tax_calculate" IN allowed_tools AND tax_calculate IN get_sdk_tools()_
    - _Preservation: classify_account 和 generate_mcp_voucher 工具不受影响_
    - _Requirements: 2.6, 2.7_

  - [x] 3.4 Update `_SYSTEM_PROMPT` (core.py)
    - 移除工作流第 2 步 "若用户上传了发票图片，调用 ocr_invoice 工具识别发票文字" 的指令
    - 更新为说明 OCR 已在预处理阶段完成，prompt 中已包含识别文字
    - 避免 Agent 在收到已包含 OCR 文字的 prompt 后仍尝试调用 `ocr_invoice` 工具造成重复 OCR
    - _Requirements: 2.1_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - 图片上传经 OCR 识别后进入 prompt 且工具注册完整
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - 非图片请求及已有工具行为不变
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - 确认 `aiohttp` 依赖已添加到 `requirements.txt`（`OCRService._call_cloud` 使用了 `aiohttp`，当前 `requirements.txt` 中只有 `httpx`，缺少 `aiohttp` 会导致导入错误）
  - Run full test suite to confirm no regressions
  - Ensure exploration tests (Property 1) pass after fix
  - Ensure preservation tests (Property 2) still pass after fix
  - Ensure existing unit tests in `tests/` directory still pass
  - Ask the user if questions arise
