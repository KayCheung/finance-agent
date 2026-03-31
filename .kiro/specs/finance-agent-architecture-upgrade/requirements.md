# 需求文档：财务报销 Agent 系统架构升级

## 简介

本文档定义了"基于 Claude Agent SDK + PaddleOCR 的发票报销自动生成凭证系统"的全面架构升级需求。升级分为三个阶段：短期优化（确定性计算、安全合规、会话持久化、OCR 双模式统一架构、科目匹配升级）、中期扩展（批量报销、OA 对接、历史查询、多票据类型）、长期方向（前端迁移、Agent 能力扩展、子 Agent 可嵌入性）。

## 术语表

- **Finance_Agent**: 基于 Claude Agent SDK 的核心财务报销智能代理，负责协调 OCR 识别、科目分类、凭证生成等工具调用
- **Tax_Calculator**: 价税分离确定性计算工具函数，根据金额和税率计算不含税价款与税额
- **OCR_Service**: 发票图片文字识别服务，支持 PaddleOCR-VL 云端模式（cloud_vl）和 PaddleOCR 本地模式（local）双模式运行，云端不可用时自动降级到本地
- **Session_Store**: 会话持久化存储模块，采用插件式架构设计，内置 JSON/YAML 文件存储后端，支持扩展为 Redis 等其他存储后端
- **Account_Classifier**: 会计科目匹配模块，支持三种匹配策略：硬编码关键词规则、RAG 检索增强生成、LLM 推理（通过外部 MCP 接口获取科目列表后由 LLM 推理匹配）
- **Voucher_Generator**: 凭证生成器，将确认后的报销数据封装为 MCP 标准报文
- **Batch_Processor**: 批量报销处理模块，支持多张发票的并行识别、合并或分别生成凭证
- **OA_Connector**: 企业 OA 系统对接模块，负责将凭证提交至审批流
- **Ticket_Parser**: 多票据类型解析器，针对增值税专票、普票、电子发票、火车票、机票行程单等差异化处理
- **Budget_Checker**: 预算校验模块（可选），在生成凭证前检查部门预算余额，可通过配置启用或禁用
- **Compliance_Checker**: 合规检查模块，校验报销是否符合企业财务制度
- **Approval_Advisor**: 智能审批建议模块，基于历史数据和规则为审批人提供建议
- **RAG_Engine**: 检索增强生成引擎，用于科目匹配和智能问答
- **VoucherRepository**: 凭证数据仓库模块，独立于 SessionBackend，提供凭证的多维度查询和检索能力（按 ID、日期、部门、报销人等），支撑历史查询和合规/审批模块的数据需求
- **Agent_Core**: Finance Agent 的核心能力层，与 HTTP 网关和前端解耦，可作为独立子 Agent 被企业级 Orchestrator Agent 调用
- **Orchestrator_Agent**: 企业级多 Agent 编排系统，负责将用户请求路由到对应的子 Agent（如财务报销、合同管理、人事审批等）

---

## 需求

### 需求 1：价税分离确定性计算

**用户故事：** 作为财务人员，我希望价税分离计算由确定性工具函数完成而非 AI 推理，以确保计算结果精确可靠。

#### 验收标准

1. WHEN 用户提供含税总额和税率时，THE Tax_Calculator SHALL 使用公式"不含税价款 = 含税总额 / (1 + 税率)"计算不含税价款，精确到小数点后两位
2. WHEN 用户提供含税总额和税率时，THE Tax_Calculator SHALL 使用公式"税额 = 含税总额 - 不含税价款"计算税额
3. THE Tax_Calculator SHALL 确保"不含税价款 + 税额 = 含税总额"恒等式成立（借贷平衡不变量）
4. WHEN 税率为 0 或未提供税率时，THE Tax_Calculator SHALL 将含税总额直接作为不含税价款，税额设为 0
5. IF 含税总额为负数或非数值类型，THEN THE Tax_Calculator SHALL 返回明确的错误信息，包含参数名称和期望类型
6. THE Finance_Agent SHALL 调用 Tax_Calculator 工具函数获取价税分离结果，而非在系统提示词中由 AI 推理计算

---

### 需求 2：图片处理内网安全约束

**用户故事：** 作为企业安全管理员，我希望发票图片处理全程在内网完成，不经过外网传输，以满足企业信息安全要求。

#### 验收标准

1. THE OCR_Service SHALL 仅通过内网地址调用 PaddleOCR 服务，禁止将图片数据发送至任何外网 API
2. THE Finance_Agent SHALL 不使用任何 Vision API（如 Claude Vision、GPT-4V 等）处理发票图片
3. WHEN 发票图片上传时，THE Finance_Agent SHALL 仅将图片传递给内网 OCR_Service 进行文字识别
4. THE OCR_Service SHALL 在配置中明确指定内网服务地址，且地址格式校验通过后方可启动服务

---

### 需求 3：会话持久化存储（插件式架构）

**用户故事：** 作为用户，我希望会话数据持久化存储，以便服务重启后能恢复之前的会话上下文；作为架构师，我希望存储后端可插拔替换，以便后续平滑迁移到 Redis 等方案。

#### 验收标准

1. THE Session_Store SHALL 采用插件式架构，定义统一的存储后端抽象接口（SessionBackend），包含 save、load、delete、list、get_latest 方法
2. THE Session_Store SHALL 内置 JSON 文件存储后端（FileSessionBackend）和 YAML 文件存储后端（YamlSessionBackend）作为默认实现
3. THE Session_Store SHALL 支持通过配置项指定使用的存储后端类名，实现后端切换无需修改业务代码
4. WHEN 新会话创建时，THE Session_Store SHALL 通过当前存储后端持久化会话数据
5. WHEN 会话状态发生变更时（如凭证草稿生成、用户确认），THE Session_Store SHALL 将最新状态同步写入存储后端
6. WHEN 服务重启后收到已有会话 ID 的请求时，THE Session_Store SHALL 从存储后端加载该会话的历史上下文
7. WHEN 用户打开界面且未指定会话 ID 时，THE Session_Store SHALL 通过 get_latest 方法自动加载最后一次活跃会话的完整内容（包括对话记录和凭证状态）
8. IF 会话数据读取失败（文件损坏、格式错误或后端不可用），THEN THE Session_Store SHALL 记录错误日志并创建新的空会话，同时通知用户历史上下文已丢失
9. WHEN 会话被用户主动删除时，THE Session_Store SHALL 通过存储后端删除对应的会话数据
10. THE SessionBackend 抽象接口 SHALL 预留 Redis 存储后端（RedisSessionBackend）的扩展能力，确保接口设计兼容键值存储模式

---

### 需求 4：OCR 服务统一架构（双模式 + 降级）

**用户故事：** 作为系统架构师，我希望 OCR 服务支持 PaddleOCR-VL 云端和 PaddleOCR 本地双模式运行，并在云端不可用时自动降级到本地，以兼顾识别精度、离线可用性和业务连续性。

#### 验收标准

1. THE OCR_Service SHALL 支持两种运行模式：PaddleOCR-VL 云端模式（cloud_vl）和 PaddleOCR 本地模式（local），通过配置项指定优先模式
2. WHEN 使用云端模式时，THE OCR_Service SHALL 调用 PaddleOCR-VL 云端 API，该 API 部署在企业内网环境中
3. WHEN 使用本地模式时，THE OCR_Service SHALL 加载本地 PaddleOCR 模型文件进行推理
4. WHEN 云端模式调用超时（超过配置的超时阈值）或返回错误时，THE OCR_Service SHALL 自动降级到本地模式进行识别
5. THE OCR_Service SHALL 支持通过配置项分别设置云端和本地模式的超时阈值（云端默认 30 秒，本地默认 60 秒）和重试次数（默认 1 次）
6. WHEN 降级发生后云端服务恢复可用时，THE OCR_Service SHALL 在下一次调用时自动切换回云端模式
7. THE OCR_Service SHALL 在返回结果中标注使用的模式（"cloud_vl" 或 "local"）和识别耗时
8. IF 云端和本地模式均不可用（本地模型加载失败），THEN THE OCR_Service SHALL 返回明确的错误信息"OCR 服务完全不可用，请联系运维"
9. THE OCR_Service SHALL 记录每次降级事件的时间戳、错误原因和降级持续时长到日志中

---

### 需求 5：科目匹配多策略升级

**用户故事：** 作为财务人员，我希望科目匹配能基于企业历史数据、会计准则和 LLM 推理智能推荐，而非仅依赖硬编码关键词。

#### 验收标准

1. THE Account_Classifier SHALL 支持三种匹配策略：关键词规则模式（当前）、RAG 检索模式、LLM 推理模式，通过配置项指定优先策略和降级链（如 "rag → llm → keyword"）
2. WHEN 使用 RAG 模式时，THE RAG_Engine SHALL 从科目知识库中检索与费用描述最相关的前 3 个候选科目
3. WHEN 使用 LLM 推理模式时，THE Account_Classifier SHALL 通过外部 MCP 接口获取企业完整科目列表，然后由 LLM 基于费用描述和科目列表进行推理匹配
4. THE Account_Classifier SHALL 支持通过 MCP 工具调用外部科目管理系统，获取最新的科目代码、名称和适用范围
5. WHEN RAG 模式返回的最高相似度低于配置的置信度阈值时，THE Account_Classifier SHALL 按降级链切换到下一策略（LLM 推理）
6. WHEN LLM 推理模式调用失败（MCP 接口超时、科目列表获取失败或 LLM 返回结果不在科目列表中）时，THE Account_Classifier SHALL 按降级链切换到下一策略（关键词规则）
7. THE Account_Classifier SHALL 在返回结果中包含匹配策略（"rag"、"llm" 或 "keyword"）、置信度分数和降级路径（如 "rag→llm→keyword" 表示经历了两次降级）
8. IF 降级链中所有高优先级策略均不可用，THEN THE Account_Classifier SHALL 最终回退到关键词规则模式（作为兜底策略，始终可用）并记录完整降级日志

---

### 需求 6：批量报销处理

**用户故事：** 作为报销人员，我希望一次上传多张发票后系统能自动识别并生成凭证，以提高批量报销效率。

#### 验收标准

1. WHEN 用户一次上传多张发票图片时，THE Batch_Processor SHALL 对每张发票独立调用 OCR_Service 进行识别
2. WHEN 所有发票识别完成后，THE Batch_Processor SHALL 按票据类型和费用科目对发票进行分组
3. WHEN 同一科目下存在多张发票时，THE Batch_Processor SHALL 提供两种处理策略供用户选择：合并生成一张凭证或分别生成独立凭证
4. WHEN 选择合并策略时，THE Voucher_Generator SHALL 将同科目发票的金额汇总，生成一张包含多条借方分录的凭证，且借贷总额保持平衡
5. THE Batch_Processor SHALL 在处理过程中实时返回每张发票的识别状态（排队中、识别中、识别成功、识别失败）
6. IF 批量处理中某张发票识别失败，THEN THE Batch_Processor SHALL 跳过该发票继续处理其余发票，并在最终结果中标注失败发票及失败原因
7. WHEN 批量处理完成后，THE Batch_Processor SHALL 返回处理摘要，包含：总发票数、成功数、失败数、生成凭证数、总金额
8. THE Batch_Processor SHALL 支持单次上传至少 20 张发票
9. THE Batch_Processor SHALL 控制 OCR 并发调用数不超过配置的最大并发度（默认 3），避免打爆 OCR 服务
10. THE Batch_Processor SHALL 对单次批量处理设置总超时上限（默认 300 秒），超时后终止未完成的识别任务并返回已完成的结果
11. THE Batch_Processor SHALL 对单张发票的处理内存占用进行限制，单张图片 base64 大小不超过 10MB，超出时拒绝该发票并在结果中标注原因

---

### 需求 7：企业 OA 系统对接

**用户故事：** 作为报销人员，我希望凭证确认后能自动提交到企业 OA 审批流，无需手动在 OA 系统中重复录入。

#### 验收标准

1. WHEN 用户确认凭证并触发提交时，THE OA_Connector SHALL 将凭证数据按 OA 系统要求的格式封装并提交至审批接口
2. WHEN OA 系统返回提交成功时，THE OA_Connector SHALL 将审批单号回写到凭证记录中
3. THE OA_Connector SHALL 支持通过配置文件定义 OA 系统的接口地址、认证方式和字段映射规则
4. IF OA 系统接口调用失败，THEN THE OA_Connector SHALL 将凭证状态标记为"提交失败"，记录错误详情，并支持用户手动重试
5. WHEN OA 审批状态发生变更时（审批通过、驳回、退回修改），THE OA_Connector SHALL 通过回调 Webhook 机制同步更新本地凭证状态，OA 系统调用本系统提供的回调接口推送状态变更
6. THE OA_Connector SHALL 提供 Webhook 回调端点（POST /oa/callback），接收 OA 系统推送的审批状态变更通知，并校验请求签名防止伪造
7. IF OA 系统不支持 Webhook 回调，THEN THE OA_Connector SHALL 降级为定时轮询模式，通过配置项设置轮询间隔（默认 60 秒），并在日志中标注当前使用的同步模式

---

### 需求 8：历史凭证与会话查询

**用户故事：** 作为财务人员，我希望能查询历史生成的凭证和过往会话记录，以便审计追溯和数据复用。

#### 验收标准

1. THE VoucherRepository SHALL 持久化保存所有已生成凭证的完整数据，包括凭证 ID、创建时间、分录明细、审批状态，独立于 SessionBackend 的会话存储
2. WHEN 用户按凭证 ID、日期范围、部门、报销人等条件查询时，THE VoucherRepository SHALL 提供多维度查询接口返回符合条件的凭证列表
3. WHEN 用户查询历史会话时，THE Session_Store SHALL 返回会话列表，包含会话 ID、创建时间、最后活跃时间、关联凭证数
4. WHEN 用户选择某条历史会话时，THE Session_Store SHALL 加载该会话的完整对话记录
5. WHEN 用户打开前端界面时，THE Finance_Agent SHALL 自动调用接口获取最后一次活跃会话，并在聊天区域恢复该会话的对话记录和凭证状态
6. THE VoucherRepository SHALL 支持按关键词搜索历史凭证的摘要字段
7. THE VoucherRepository SHALL 为 Compliance_Checker 和 Approval_Advisor 提供数据查询支撑，包括：按部门和费用类型查询月度累计金额、按相似条件查询历史审批记录及通过率

---

### 需求 9：多票据类型差异化处理

**用户故事：** 作为报销人员，我希望系统能识别和处理多种票据类型（增值税专票、普票、电子发票、火车票、机票行程单等），并针对不同票据类型提取对应字段。

#### 验收标准

1. THE Ticket_Parser SHALL 支持以下票据类型的识别和解析：增值税专用发票、增值税普通发票、电子发票、火车票、机票行程单、出租车票、过路费发票
2. WHEN OCR 识别完成后，THE Ticket_Parser SHALL 根据 OCR 文本特征自动判断票据类型
3. WHEN 票据类型为增值税专用发票时，THE Ticket_Parser SHALL 提取以下字段：发票代码、发票号码、开票日期、购方名称、购方税号、销方名称、销方税号、金额、税率、税额、价税合计
4. WHEN 票据类型为火车票时，THE Ticket_Parser SHALL 提取以下字段：乘车人、出发站、到达站、车次、座位等级、票价、乘车日期
5. WHEN 票据类型为机票行程单时，THE Ticket_Parser SHALL 提取以下字段：旅客姓名、航班号、出发地、目的地、票价、燃油附加费、民航发展基金、合计金额、乘机日期
6. WHEN 票据类型为出租车票时，THE Ticket_Parser SHALL 提取以下字段：上车时间、下车时间、金额、里程
7. IF Ticket_Parser 无法识别票据类型，THEN THE Ticket_Parser SHALL 将票据标记为"未知类型"，返回 OCR 原始文本，并提示用户手动选择票据类型
8. THE Ticket_Parser SHALL 针对每种票据类型定义独立的字段校验规则（如发票号码长度、日期格式等）
9. FOR ALL 已支持的票据类型，解析后再格式化输出再解析 SHALL 产生等价的结构化对象（往返一致性）

---

### 需求 10：前端 Vue3 迁移规划

**用户故事：** 作为前端开发者，我希望将当前单文件 HTML 前端迁移到 Vue3 框架，以支持组件化开发和更好的可维护性。

#### 验收标准

1. THE Finance_Agent 前端 SHALL 使用 Vue3 + Composition API 重构，替代当前的单文件 HTML
2. THE Finance_Agent 前端 SHALL 将聊天区域、凭证编辑器、侧边栏、文件上传等功能拆分为独立的 Vue 组件
3. THE Finance_Agent 前端 SHALL 使用 Vue Router 管理页面路由，至少包含：报销对话页、历史查询页、系统设置页
4. THE Finance_Agent 前端 SHALL 使用 Pinia 进行状态管理，统一管理会话状态、凭证数据、用户信息
5. THE Finance_Agent 前端 SHALL 保持与当前 FastAPI 后端 API 的完全兼容

---

### 需求 11：Agent 能力扩展

**用户故事：** 作为企业财务管理者，我希望 Agent 具备预算校验、合规检查和智能审批建议能力，以加强财务管控和提升审批效率。

#### 验收标准

1. THE Budget_Checker SHALL 为可选模块，通过配置项（enable_budget_check: true/false）控制是否启用，默认为禁用
2. WHEN Budget_Checker 已启用且凭证草稿生成后，THE Budget_Checker SHALL 查询该部门当前预算余额，并与凭证金额进行比较
3. IF Budget_Checker 已启用且凭证金额超过部门剩余预算，THEN THE Budget_Checker SHALL 向用户发出预算超支警告，包含当前预算余额和超支金额
4. WHEN Budget_Checker 未启用时，THE Finance_Agent SHALL 跳过预算校验步骤，直接进入后续流程
5. WHEN 凭证草稿生成后，THE Compliance_Checker SHALL 根据企业财务制度规则校验凭证合规性
6. THE Compliance_Checker SHALL 至少检查以下规则：单笔报销金额上限、同一费用类型月度累计上限、票据日期有效期（如开票日期距报销日期不超过配置天数）
7. THE Compliance_Checker SHALL 通过 VoucherRepository 查询同一部门、同一费用类型的月度累计金额，作为"月度累计上限"规则的数据来源
8. IF 凭证存在合规问题，THEN THE Compliance_Checker SHALL 返回具体违规项和对应的制度条款
9. WHEN 凭证提交审批前，THE Approval_Advisor SHALL 基于历史审批数据生成审批建议（建议通过、建议关注、建议驳回）
10. THE Approval_Advisor SHALL 通过 VoucherRepository 查询历史相似凭证的审批记录（按部门、科目、金额区间匹配），作为审批建议的数据来源
11. THE Approval_Advisor SHALL 在审批建议中说明判断依据，包括参考的历史相似案例数量和通过率

---

### 需求 12：子 Agent 可嵌入性设计

**用户故事：** 作为企业架构师，我希望 Finance Agent 能作为子 Agent 嵌入到企业级多 Agent 编排系统中，以便与其他业务 Agent（合同、人事、采购等）协同工作。

#### 验收标准

1. THE Finance_Agent SHALL 将核心业务逻辑（Agent_Core）与 HTTP 网关层（FastAPI）和前端层（HTML/Vue）完全解耦，形成独立可导入的 Python 模块
2. THE Agent_Core SHALL 暴露标准化的调用接口，包含：invoke(request) 异步方法，接收结构化的报销请求，返回结构化的处理结果
3. THE Agent_Core SHALL 定义能力声明（Capability Declaration），包含：agent_name、description、supported_intents（如 "invoice_reimbursement"、"voucher_query"、"batch_reimbursement"）、input_schema、output_schema
4. WHEN 被 Orchestrator_Agent 调用时，THE Agent_Core SHALL 接受外部传入的会话上下文（session_context），而非仅依赖内部会话管理
5. THE Agent_Core SHALL 支持两种运行模式：独立模式（自带 HTTP 网关和前端，当前形态）和嵌入模式（作为子 Agent 被上层系统调用，无 HTTP 层）
6. WHEN 运行在嵌入模式时，THE Agent_Core SHALL 通过 MCP 协议将自身的工具（ocr_invoice、classify_account、generate_mcp_voucher、tax_calculate）注册为可被 Orchestrator_Agent 发现和调用的 MCP 工具
7. THE Agent_Core SHALL 定义标准化的事件回调接口（on_voucher_created、on_voucher_confirmed、on_voucher_submitted），供 Orchestrator_Agent 监听关键业务事件
8. THE Agent_Core SHALL 支持接收 Orchestrator_Agent 传递的用户身份信息（user_id、department、role），而非仅从对话文本中提取
