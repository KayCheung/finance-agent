# Image Upload OCR Fix — Bugfix Design

## Overview

用户上传发票图片后系统报错 "Prompt is too long"，根本原因是 `_process_request` 将完整 base64 图片数据直接拼入 prompt 而未调用 `OCRService.recognize()`。同时存在三个关联缺陷：`ocr_invoice` 工具绕过 `OCRService` 直接调用远程 API、`_create_sdk_client` 的 `allowed_tools` 缺少 `tax_calculate`、`get_sdk_tools()` 未返回 `tax_calculate` 对应的 `@tool` 函数。

修复策略：在 `_process_request` 中引入 `OCRService` 进行图片预处理，将 OCR 文字结果（而非 base64）放入 prompt；重构 `ocr_invoice` 工具使其委托 `OCRService`；补全 `tax_calculate` 的工具注册。

## Glossary

- **Bug_Condition (C)**: 触发 bug 的条件——用户上传图片时 base64 数据被直接拼入 prompt，或工具注册不完整
- **Property (P)**: 期望行为——图片经 OCR 识别后以文字形式进入 prompt，所有工具正确注册
- **Preservation**: 不受修复影响的现有行为——纯文字消息处理、凭证 JSON 解析、空消息提示、异常捕获、已有工具签名
- **`_process_request`**: `agent_core/core.py` 中处理用户请求的核心方法，构建 prompt 并调用 Agent SDK
- **`OCRService`**: `tools/ocr_service.py` 中的统一 OCR 服务，支持云端/本地双模式、自动降级、内网校验
- **`ocr_invoice`**: `agent_core/_tools.py` 中的 SDK 工具函数，供 Agent 调用以识别发票图片
- **`get_sdk_tools()`**: `agent_core/_tools.py` 中返回所有 `@tool` 函数列表的函数
- **`_create_sdk_client`**: `agent_core/core.py` 中创建 `ClaudeSDKClient` 并配置 `allowed_tools` 的方法

## Bug Details

### Bug Condition

本次修复涉及四个相互关联的缺陷：

**缺陷 1（核心）**：`_process_request` 在处理上传图片时，将完整 base64 数据（几十万字符）直接拼入 prompt 文本，未调用 `OCRService.recognize()` 进行 OCR 识别，导致 prompt 超长触发 "Prompt is too long" 错误。

**缺陷 2**：`ocr_invoice` 工具直接使用 `requests.post` 调用远程 OCR API，绕过了 `OCRService` 的双模式切换、自动降级、内网地址校验和降级日志记录能力。

**缺陷 3**：`_create_sdk_client` 的 `allowed_tools` 列表缺少 `mcp__finance-tools__tax_calculate`，导致 Agent 无法调用价税分离工具。

**缺陷 4**：`get_sdk_tools()` 返回列表中缺少 `tax_calculate` 对应的 `@tool` 函数，导致该工具无法被注册到 MCP Server。

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type AgentRequest | ToolCall | SDKClientConfig
  OUTPUT: boolean

  // 缺陷 1 & 2: 图片上传时 OCR 未正确调用
  IF input IS AgentRequest THEN
    RETURN input.images IS NOT EMPTY
           AND (base64DataInPrompt(input) OR ocrServiceNotCalled(input))
  END IF

  // 缺陷 3: allowed_tools 不完整
  IF input IS SDKClientConfig THEN
    RETURN "mcp__finance-tools__tax_calculate" NOT IN input.allowed_tools
  END IF

  // 缺陷 4: get_sdk_tools 返回不完整
  IF input IS ToolRegistration THEN
    RETURN "tax_calculate" NOT IN [t.name FOR t IN get_sdk_tools()]
  END IF

  RETURN FALSE
END FUNCTION
```

### Examples

- 用户上传一张 500KB 的发票图片（base64 约 680K 字符），系统将 680K 字符拼入 prompt → 触发 "Prompt is too long" 错误。期望：调用 OCRService 识别后，仅将几百字的 OCR 文字放入 prompt。
- 用户上传图片并附带消息 "帮我报销这张发票"，base64 + 消息一起超长 → 同样报错。期望：OCR 文字 + 用户消息组成合理长度的 prompt。
- Agent 调用 `ocr_invoice` 工具，该工具直接 `requests.post` 到远程 URL → 云端不可用时无降级。期望：通过 `OCRService.recognize()` 获得自动降级能力。
- Agent 尝试调用 `tax_calculate` 工具 → 被 `allowed_tools` 拦截，无法执行。期望：工具正常注册并可调用。

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- 用户仅发送文字消息（不上传图片）时，系统正常处理并返回 AI 回复
- AI 回复中包含 `%%VOUCHER_JSON_START%%...%%VOUCHER_JSON_END%%` 时，凭证 JSON 正确解析
- 用户发送空消息且无图片时，返回提示 "请输入您的问题或上传发票图片"
- Agent SDK 调用异常时，捕获异常并返回包含错误信息的 `AgentResponse`
- `classify_account` 和 `generate_mcp_voucher` 工具的原有逻辑和签名不变
- 已有三个工具通过 MCP 协议调用时，保持原有工具签名和返回格式

**Scope:**
所有不涉及图片上传的请求路径、不涉及 `tax_calculate` 工具的调用路径，均不受本次修复影响。具体包括：
- 纯文字对话请求
- 空消息请求
- `classify_account` / `generate_mcp_voucher` 工具调用
- 凭证 JSON 解析逻辑
- 异常处理逻辑

## Hypothesized Root Cause

基于代码分析，四个缺陷的根因如下：

1. **`_process_request` 未集成 OCRService**：从旧版 `finance_agent.py` 迁移时，prompt 构建逻辑直接将 base64 数据拼入文本（第 270-278 行），意图是让 Agent 自行调用 `ocr_invoice` 工具，但完整 base64 已经超出 prompt 长度限制。正确做法是在构建 prompt 前先调用 `OCRService.recognize()` 完成 OCR，将识别文字放入 prompt。

2. **`ocr_invoice` 工具直接调用远程 API**：该工具从旧版迁移时保留了 `requests.post` 直接调用远程 OCR 的实现（第 44-54 行），未适配新的 `OCRService` 统一架构。`OCRService` 提供的双模式切换、自动降级、内网校验等能力被完全绕过。

3. **`allowed_tools` 列表遗漏**：`_create_sdk_client` 方法在配置 `ClaudeAgentOptions` 时，`allowed_tools` 只列出了三个工具（第 378-382 行），遗漏了 `mcp__finance-tools__tax_calculate`，尽管 `_MCP_TOOL_DEFINITIONS` 中已定义了该工具。

4. **`get_sdk_tools()` 返回列表不完整**：`_tools.py` 文件中缺少 `tax_calculate` 对应的 `@tool` 装饰器函数定义，`get_sdk_tools()` 自然无法返回它。需要新增一个调用 `tools.tax_calculator.calculate_tax` 的 `@tool` 函数。

## Correctness Properties

Property 1: Bug Condition - 图片上传经 OCR 识别后进入 prompt

_For any_ `AgentRequest` 其中 `images` 非空，修复后的 `_process_request` SHALL 调用 `OCRService.recognize()` 对每张图片进行 OCR 识别，并将识别出的文字内容（而非 base64 原始数据）放入 prompt。prompt 中不应包含完整的 base64 字符串。

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Bug Condition - ocr_invoice 工具委托 OCRService

_For any_ `ocr_invoice` 工具调用，修复后的实现 SHALL 通过 `OCRService.recognize()` 执行 OCR 识别，获得双模式切换、自动降级、内网校验和降级日志记录等完整能力，而非直接使用 `requests.post`。

**Validates: Requirements 2.5**

Property 3: Bug Condition - tax_calculate 工具完整注册

_For any_ `_create_sdk_client` 调用，`allowed_tools` 列表 SHALL 包含 `mcp__finance-tools__tax_calculate`；且 `get_sdk_tools()` 返回的列表 SHALL 包含 `tax_calculate` 对应的 `@tool` 函数。

**Validates: Requirements 2.6, 2.7**

Property 4: Preservation - 非图片请求行为不变

_For any_ `AgentRequest` 其中 `images` 为空（纯文字消息或空消息），修复后的 `_process_request` SHALL 产生与修复前完全相同的行为，包括 prompt 构建、Agent 调用、凭证解析和错误处理。

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

Property 5: Preservation - 已有工具行为不变

_For any_ `classify_account` 或 `generate_mcp_voucher` 工具调用，修复后的代码 SHALL 保持原有的工具签名、参数格式和返回格式不变。

**Validates: Requirements 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `agent_core/core.py`

**Function**: `_process_request`

**Specific Changes**:
1. **引入 OCRService 依赖**：在 `AgentCore.__init__` 中接收或创建 `OCRService` 实例（基于 `AgentConfig` 中的 OCR 配置）
2. **图片预处理替换**：将当前直接拼接 base64 的逻辑（第 270-278 行）替换为：
   - 对每张图片调用 `self._ocr_service.recognize(image_bytes, filename)`
   - 将返回的 `OCRResult.raw_text` 放入 prompt
   - 记录 OCR 执行日志（模式、耗时、字符数）
3. **OCR 失败处理**：捕获 `OCRUnavailableError`，返回友好错误提示而非让 prompt 超长报错
4. **base64 解码**：在调用 OCR 前将 `image_base64` 字符串解码为 `bytes`

**File**: `agent_core/core.py`

**Function**: `_create_sdk_client`

**Specific Changes**:
5. **补全 allowed_tools**：在 `allowed_tools` 列表中添加 `"mcp__finance-tools__tax_calculate"`

**File**: `agent_core/_tools.py`

**Function**: `ocr_invoice`

**Specific Changes**:
6. **委托 OCRService**：移除 `requests.post` 直接调用逻辑，改为通过 `OCRService.recognize()` 执行 OCR
7. **OCRService 实例管理**：在 `_tools.py` 中定义模块级变量 `_ocr_service: Optional[OCRService] = None` 和设置函数 `set_ocr_service(instance: OCRService) -> None`。由 `AgentCore.__init__` 在创建 `OCRService` 实例后调用 `_tools.set_ocr_service(instance)` 进行设置。`ocr_invoice` 工具函数内部通过读取模块级变量 `_ocr_service` 获取实例。此方案避免了 `_tools.py` 直接导入 `config.py` 带来的循环导入风险（`_tools.py` 被 `core.py` 导入，`core.py` 又依赖 `config.py`），也绕开了 `@tool` 装饰器函数签名 `async def ocr_invoice(args: dict) -> dict` 无法直接注入依赖的限制。
8. **移除冗余依赖**：移除 `requests` 和 `REMOTE_OCR_URL` / `REMOTE_OCR_TOKEN` 等不再需要的导入和变量

**File**: `agent_core/_tools.py`

**Function**: `get_sdk_tools`（及新增 `tax_calculate` 工具函数）

**Specific Changes**:
9. **新增 `tax_calculate` @tool 函数**：定义一个调用 `tools.tax_calculator.calculate_tax` 的 `@tool` 装饰器函数，接收 `total_amount` 和 `tax_rate` 参数。注意：`_MCP_TOOL_DEFINITIONS` 中这两个参数的类型为 `"type": "string"`（Decimal 字符串），而 `calculate_tax` 函数接收 `Decimal` 类型，因此 `@tool` 函数内部必须进行类型转换：`Decimal(str(total_amount))` 和 `Decimal(str(tax_rate))`，确保从 MCP 传入的字符串参数正确转为 `Decimal` 后再调用底层函数。
10. **更新 `get_sdk_tools()` 返回列表**：将 `tax_calculate` 函数加入返回列表

**File**: `agent_core/core.py`

**Constant**: `_SYSTEM_PROMPT`

**Specific Changes**:
11. **更新系统提示词工作流描述**：移除 `_SYSTEM_PROMPT` 中工作流第 2 步"若用户上传了发票图片，调用 ocr_invoice 工具识别发票文字"的指令，改为说明 OCR 已在预处理阶段完成，prompt 中已包含识别文字。这是因为修复后 `_process_request` 会在构建 prompt 前先调用 `OCRService.recognize()`，将 OCR 文字直接放入 prompt，如果不同步更新 `_SYSTEM_PROMPT`，Agent 在收到已包含 OCR 文字的 prompt 后仍会尝试调用 `ocr_invoice` 工具，造成重复 OCR。
12. **修改 prompt 构建方式**：在 `_process_request` 构建 prompt 时，对 OCR 识别结果使用明确的标记格式（如 `"以下是 OCR 识别结果：\n{ocr_text}"`），让 Agent 清楚知道 OCR 已完成，无需再调用 `ocr_invoice` 工具。

## Testing Strategy

### Validation Approach

测试策略分两阶段：先在未修复代码上验证 bug 存在（探索性测试），再在修复后验证正确性和行为保持。

### Exploratory Bug Condition Checking

**Goal**: 在实施修复前，通过测试确认 bug 的存在并验证根因分析。

**Test Plan**: 编写测试模拟图片上传场景，验证 prompt 中包含 base64 数据、OCRService 未被调用、allowed_tools 不完整、get_sdk_tools 缺少 tax_calculate。

**Test Cases**:
1. **Prompt 超长测试**：构造包含图片的 `AgentRequest`，验证 `_process_request` 构建的 prompt 包含完整 base64 数据（will fail on unfixed code — prompt 包含 base64）
2. **OCR 未调用测试**：Mock `OCRService.recognize`，验证上传图片时该方法未被调用（will fail on unfixed code — OCR 未被调用）
3. **ocr_invoice 直接调用测试**：验证 `ocr_invoice` 工具使用 `requests.post` 而非 `OCRService`（will fail on unfixed code — 直接调用远程 API）
4. **allowed_tools 完整性测试**：验证 `_create_sdk_client` 的 `allowed_tools` 缺少 `tax_calculate`（will fail on unfixed code）
5. **get_sdk_tools 完整性测试**：验证 `get_sdk_tools()` 返回列表中无 `tax_calculate`（will fail on unfixed code）

**Expected Counterexamples**:
- `_process_request` 构建的 prompt 长度超过 100K 字符（包含 base64 数据）
- `OCRService.recognize` 调用次数为 0
- `ocr_invoice` 内部调用 `requests.post`
- `allowed_tools` 长度为 3（缺少 tax_calculate）
- `get_sdk_tools()` 返回长度为 3（缺少 tax_calculate）

### Fix Checking

**Goal**: 验证修复后，所有 bug 条件下的输入均产生期望行为。

**Pseudocode:**
```
FOR ALL request WHERE request.images IS NOT EMPTY DO
  result := _process_request_fixed(request)
  ASSERT OCRService.recognize WAS CALLED FOR EACH IMAGE
  ASSERT prompt DOES NOT CONTAIN base64 data
  ASSERT prompt CONTAINS ocr_text
  ASSERT result.success == True OR result HAS friendly_error
END FOR

FOR ALL tool_call WHERE tool_call.name == "ocr_invoice" DO
  result := ocr_invoice_fixed(tool_call.args)
  ASSERT OCRService.recognize WAS CALLED
  ASSERT requests.post WAS NOT CALLED
END FOR

FOR ALL config WHERE config IS SDKClientConfig DO
  ASSERT "mcp__finance-tools__tax_calculate" IN config.allowed_tools
  ASSERT "tax_calculate" IN [t.name FOR t IN get_sdk_tools()]
END FOR
```

### Preservation Checking

**Goal**: 验证修复后，所有非 bug 条件下的输入产生与修复前相同的结果。

**Pseudocode:**
```
FOR ALL request WHERE request.images IS EMPTY DO
  ASSERT _process_request_original(request) == _process_request_fixed(request)
END FOR

FOR ALL tool_call WHERE tool_call.name IN ["classify_account", "generate_mcp_voucher"] DO
  ASSERT tool_original(tool_call.args) == tool_fixed(tool_call.args)
END FOR
```

**Testing Approach**: 属性基测试（PBT）适用于保持性检查，因为：
- 自动生成大量测试用例覆盖输入域
- 捕获手动单元测试可能遗漏的边界情况
- 对非 bug 输入的行为不变性提供强保证

**Test Plan**: 先在未修复代码上观察纯文字消息、空消息、已有工具调用的行为，再编写 PBT 验证修复后行为一致。

**Test Cases**:
1. **纯文字消息保持**：验证不含图片的请求在修复前后产生相同的 prompt 和响应
2. **空消息保持**：验证空消息请求在修复前后返回相同的提示文本
3. **凭证解析保持**：验证包含 VOUCHER_JSON 的回复在修复前后正确解析
4. **异常处理保持**：验证 Agent SDK 异常在修复前后产生相同的错误响应
5. **已有工具签名保持**：验证 `classify_account` 和 `generate_mcp_voucher` 的参数和返回格式不变

### Unit Tests

- 测试 `_process_request` 处理含图片请求时调用 OCRService 并将 OCR 文字放入 prompt
- 测试 `_process_request` 处理含图片请求时 OCR 失败返回友好错误
- 测试 `_process_request` 处理含图片+文字请求时正确组合 prompt
- 测试 `ocr_invoice` 工具通过 OCRService 执行 OCR
- 测试 `tax_calculate` 工具正确调用 `calculate_tax` 并返回结果
- 测试 `get_sdk_tools()` 返回包含四个工具的列表
- 测试 `_create_sdk_client` 的 `allowed_tools` 包含四个工具

### Property-Based Tests

- 生成随机 `AgentRequest`（含/不含图片），验证 prompt 中永远不包含超过 1000 字符的连续 base64 模式
- 生成随机纯文字 `AgentRequest`，验证修复前后 prompt 构建逻辑一致
- 生成随机 `classify_account` / `generate_mcp_voucher` 参数，验证工具行为不变

### Integration Tests

- 端到端测试：上传发票图片 → OCR 识别 → Agent 处理 → 返回正常回复
- 端到端测试：上传图片 + 文字消息 → OCR + 消息组合 → Agent 处理
- 端到端测试：OCR 服务不可用 → 返回友好错误提示。测试方式：通过 `unittest.mock.patch` 同时 Mock `OCRService._call_cloud` 和 `OCRService._call_local` 两个方法，使其抛出异常（如 `OCRUnavailableError` 或 `ConnectionError`），模拟云端和本地 OCR 均不可用的场景，验证系统返回友好错误提示而非未处理异常。
- 端到端测试：Agent 调用 `tax_calculate` 工具 → 正确执行价税分离计算
