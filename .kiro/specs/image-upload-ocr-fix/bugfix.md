# Bugfix Requirements Document

## Introduction

用户上传发票图片后，系统报错 "Prompt is too long"。根本原因是 `agent_core/core.py` 的 `_process_request` 方法在处理上传图片时，将完整的 base64 编码图片数据（通常几十万字符）直接拼接到 prompt 文本中，而没有先调用 `OCRService.recognize()` 进行文字识别。这导致 prompt 长度远超模型限制，触发错误。同时用户也观察到没有 OCR 执行日志，说明 OCR 服务完全没有被调用。

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 用户上传发票图片 THEN 系统将完整的 base64 编码图片数据（几十万字符）直接拼接到 prompt 文本中，导致 prompt 超长并触发 "Prompt is too long" 错误

1.2 WHEN 用户上传发票图片 THEN 系统没有调用 `OCRService.recognize()` 进行文字识别，OCR 执行日志完全缺失

1.3 WHEN 用户上传发票图片并附带文字消息 THEN 系统同样将 base64 数据拼接到 prompt 中，文字消息与超长的 base64 数据一起发送，导致相同的 "Prompt is too long" 错误

1.4 WHEN `_tools.py` 中的 `ocr_invoice` 工具被 Agent 调用 THEN 该工具直接使用 `requests.post` 调用远程 OCR 服务，完全绕过 `ocr_service.py` 中 `OCRService` 实现的双模式切换、自动降级、内网地址校验和降级日志记录等能力

1.5 WHEN `_create_sdk_client` 创建 Agent SDK 客户端 THEN `allowed_tools` 列表中缺少 `mcp__finance-tools__tax_calculate`，导致 Agent 无法调用价税分离工具（`_MCP_TOOL_DEFINITIONS` 中已定义 `tax_calculate`）

1.6 WHEN `get_sdk_tools()` 被调用以获取注册工具列表 THEN 返回的列表中只包含 `[ocr_invoice, classify_account, generate_mcp_voucher]`，缺少 `tax_calculate` 对应的 `@tool` 函数定义，导致该工具根本无法被注册和调用

### Expected Behavior (Correct)

2.1 WHEN 用户上传发票图片 THEN 系统 SHALL 先调用 `OCRService.recognize()` 对图片进行 OCR 文字识别，并将识别出的文字内容（而非 base64 原始数据）放入 prompt 中

2.2 WHEN 用户上传发票图片 THEN 系统 SHALL 产生 OCR 执行日志，包含识别模式（云端/本地）、耗时、识别字符数等信息

2.3 WHEN 用户上传发票图片并附带文字消息 THEN 系统 SHALL 将 OCR 识别出的文字与用户消息一起组成 prompt，prompt 长度保持在合理范围内

2.4 WHEN OCR 识别失败（云端和本地均不可用）THEN 系统 SHALL 返回友好的错误提示，告知用户 OCR 服务不可用，而非触发 "Prompt is too long" 错误

2.5 WHEN `_tools.py` 中的 `ocr_invoice` 工具被 Agent 调用 THEN 该工具 SHALL 通过 `OCRService.recognize()` 执行 OCR 识别，从而获得双模式切换、自动降级、内网地址校验和降级日志记录等完整能力

2.6 WHEN `_create_sdk_client` 创建 Agent SDK 客户端 THEN `allowed_tools` 列表 SHALL 包含 `mcp__finance-tools__tax_calculate`，使 Agent 能够调用价税分离工具

2.7 WHEN `get_sdk_tools()` 被调用以获取注册工具列表 THEN 返回的列表 SHALL 包含 `tax_calculate` 对应的 `@tool` 函数，使该工具能够被正确注册到 MCP Server 并被 Agent 调用

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 用户仅发送文字消息（不上传图片）THEN 系统 SHALL CONTINUE TO 正常处理文字消息并返回 AI 回复

3.2 WHEN 用户上传图片后 AI 回复中包含 VOUCHER_JSON 块 THEN 系统 SHALL CONTINUE TO 正确解析凭证 JSON 数据并返回凭证预览

3.3 WHEN 用户发送空消息且无图片 THEN 系统 SHALL CONTINUE TO 返回提示 "请输入您的问题或上传发票图片"

3.4 WHEN Agent SDK 调用过程中发生异常 THEN 系统 SHALL CONTINUE TO 捕获异常并返回包含错误信息的 AgentResponse

3.5 WHEN `classify_account` 或 `generate_mcp_voucher` 工具被 Agent 调用 THEN 系统 SHALL CONTINUE TO 正常执行这些工具的原有逻辑，不受 `ocr_invoice` 重构和 `tax_calculate` 新增的影响

3.6 WHEN 已有的三个工具（`ocr_invoice`、`classify_account`、`generate_mcp_voucher`）通过 MCP 协议被调用 THEN 系统 SHALL CONTINUE TO 保持原有的工具签名和返回格式不变
