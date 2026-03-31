# Finance Agent — 企业财务报销智能凭证系统

基于 Claude Agent SDK + PaddleOCR 的发票报销自动生成凭证系统。上传发票图片、输入报销信息，系统自动 OCR 识别、AI 提取结构化字段、匹配会计科目、生成符合借贷平衡的记账凭证，确认后输出 MCP 标准报文。

## 核心能力

- **发票 OCR 识别**：三模式路由（AUTO / LOCAL / REMOTE），云端不可用时自动降级到本地 PaddleOCR
- **本地 PaddleOCR 推理**：懒加载引擎、线程池异步推理、超时控制，无需云端即可离线识别
- **多票据类型**：增值税专票/普票、电子发票、火车票、机票行程单、出租车票、过路费发票
- **智能科目匹配**：RAG → LLM → 关键词三策略降级链
- **确定性价税分离**：Decimal 精确计算，保证借贷平衡恒等式
- **交互式凭证编辑**：前端可编辑分录、增删行、撤销/重做，实时借贷平衡校验
- **批量报销**：一次上传多张发票，并发控制 + 超时管理
- **MCP 凭证协议**：生成标准化报文，对接 ERP / OA 审批流
- **子 Agent 可嵌入**：Agent_Core 解耦，支持独立运行或嵌入企业级多 Agent 系统

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    前端层                                 │
│   Vue3 SPA (Chat / History / Settings)  │  index.html   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  HTTP 网关层                              │
│   FastAPI Gateway (main.py)  │  OA Webhook 回调端点      │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              Agent 核心层 (Agent_Core)                    │
│   Finance_Agent (Claude SDK)  │  能力声明  │  事件回调    │
└──────┬───────┬───────┬───────┬───────┬──────────────────┘
       │       │       │       │       │
┌──────▼──┐ ┌──▼───┐ ┌─▼──┐ ┌──▼───┐ ┌─▼────────┐
│OCR_Svc  │ │Tax   │ │Acct│ │Ticket│ │Batch     │
│三模式   │ │Calc  │ │Cls │ │Parse │ │Processor │
│AUTO/    │ │Decimal│ │3策略│ │7类型 │ │并发控制  │
│LOCAL/   │ └──────┘ └────┘ └──────┘ └──────────┘
│REMOTE   │
└─────────┘
       │
┌──────▼────────────────────────────────────────────────┐
│                   数据层                                │
│  Session_Store (插件式)  │  VoucherRepository  │  RAG  │
│  JSON / YAML / Redis     │  凭证多维查询        │ 科目库│
└───────────────────────────────────────────────────────┘
```

## OCR 三模式路由

OCR 服务支持三种运行模式，通过 `config.yaml` 中的 `ocr.preferred_mode` 配置：

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `auto` | 先尝试云端，失败自动降级到本地 PaddleOCR | 生产环境（推荐默认） |
| `local` | 仅使用本地 PaddleOCR，不调用云端 | 离线部署、无网络环境 |
| `remote` | 仅使用云端 API，不调用本地 | 无 GPU、不想安装 PaddleOCR |

向后兼容旧值 `cloud_vl`（等价于 `remote`）。

本地模式特性：
- 懒加载：首次调用时才初始化 PaddleOCR 引擎，不影响启动速度
- 线程池推理：`run_in_executor` 异步执行，不阻塞事件循环
- 超时控制：`asyncio.wait_for` 强制超时，避免推理卡死
- 优雅降级：PaddleOCR 未安装时仅影响本地模式，云端和应用启动不受影响

## 目录结构

```
finance-agent/
├── main.py                     # FastAPI 网关
├── config.yaml                 # 统一配置文件
├── requirements.txt            # Python 依赖
├── .env                        # 环境变量（API Key 等）
├── agent_core/
│   ├── core.py                 # Agent_Core 入口，能力声明，事件回调
│   ├── _tools.py               # MCP 工具定义（OCR、科目匹配、凭证生成、价税计算）
│   ├── finance_agent.py        # Claude Agent SDK 集成
│   ├── config.py               # Pydantic 配置模型 + YAML 加载
│   └── models.py               # 共享数据模型（OCRMode、OCRResult、VoucherDraft 等）
├── tools/
│   ├── ocr_service.py          # OCR 三模式路由 + 本地 PaddleOCR 推理 + 内网校验
│   ├── tax_calculator.py       # 确定性价税分离
│   ├── account_classifier.py   # RAG/LLM/关键词三策略降级
│   ├── voucher_type_resolver.py # 凭证类型解析（规则→RAG→LLM 兜底）
│   ├── voucher_generator.py    # 凭证生成器（单张 + 合并）
│   ├── ticket_parser.py        # 7 类票据解析
│   └── batch_processor.py      # 批量报销（并发控制 + 超时 + 大小限制）
├── storage/
│   ├── session_store.py        # 插件式会话存储
│   ├── backends/
│   │   ├── base.py             # SessionBackend 抽象接口
│   │   ├── file_backend.py     # JSON 文件后端
│   │   └── yaml_backend.py     # YAML 文件后端
│   └── voucher_repository.py   # 凭证数据仓库
├── extensions/
│   ├── budget_checker.py       # 预算校验（可选）
│   ├── compliance_checker.py   # 合规检查
│   ├── approval_advisor.py     # 智能审批建议
│   └── oa_connector.py         # OA 系统对接
├── rag/
│   └── engine.py               # RAG 检索引擎
│   └── knowledge_base/
│       └── voucher_type_rules.json # 凭证类型 RAG 规则库
├── tests/                      # 254+ 测试（单元测试 + 属性测试）
└── frontend/                   # Vue3 + Pinia 前端
    └── src/
```

## 快速开始

### 环境要求

- Python 3.10+
- Anthropic API Key
- （可选）PaddleOCR 云端服务（内网部署）
- （可选）PaddleOCR + PaddlePaddle（本地推理模式）

### 安装

```bash
# 克隆项目
git clone http://test-gitlab.kltb.com.cn/tongbao-ai/finance-agent.git
cd finance-agent

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装核心依赖
pip install -r requirements.txt

# （可选）安装本地 PaddleOCR 推理依赖
pip install paddleocr paddlepaddle
```

### 配置

1. 复制环境变量文件：

```bash
cp .env.example .env
```

2. 编辑 `.env`，填入 API Key：

```env
ANTHROPIC_API_KEY=sk-ant-你的Key
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

3. 编辑 `config.yaml` 按需调整：

```yaml
ocr:
  preferred_mode: auto              # auto / local / remote（兼容旧值 cloud_vl）
  cloud_url: "http://192.168.1.100:8868/ocr"
  cloud_timeout: 30
  local_timeout: 60
  retry_count: 1
  local_lang: ch                    # PaddleOCR 识别语言
  local_use_angle_cls: true         # 方向分类器
  local_use_gpu: false              # GPU 加速
  # local_model_dir: /path/to/models  # 自定义模型目录（可选）

session:
  backend_class: "storage.backends.file_backend.FileSessionBackend"
  storage_dir: "./sessions"

account_classifier:
  strategy_chain: ["rag", "llm", "keyword"]
  confidence_threshold: 0.7

voucher_repo:
  storage_file: "./storage/vouchers.json"   # 已确认凭证持久化文件

voucher_type:
  use_rag_fallback: true                    # 规则未命中时，是否启用 RAG 回退（需 rag.enabled=true）
  rag_knowledge_file: "voucher_type_rules.json"
  rag_min_score: 0.4
  enable_llm_fallback: true                 # 规则+RAG均未命中后，是否允许使用 LLM 给出的类型作为兜底

agent:
  mode: standalone                  # standalone | embedded
  model: "claude-sonnet-4-20250514"
  max_turns: 20
```

### 运行后端

```bash
.venv\Scripts\activate

python main.py
```

后端服务启动在 `http://localhost:8001`。

### 前端开发与构建

```bash
cd frontend

# 安装前端依赖
npm install

# 开发模式（热更新，自动代理后端 API 到 localhost:8001）
npm run dev
# 访问 http://localhost:5173

# 生产构建
npm run build

# 预览构建产物
npm run preview
```

前端开发模式下 Vite 会自动将 `/agent`、`/sessions`、`/vouchers`、`/oa` 路径代理到后端 `http://localhost:8001`，无需额外配置跨域。

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/agent/chat` | 发送消息 / 上传发票 |
| DELETE | `/agent/session/{id}` | 删除会话 |
| GET | `/agent/health` | 健康检查 |

## 测试

项目包含 254+ 测试，覆盖单元测试和基于 Hypothesis 的属性测试：

```bash
# 运行全部测试
python -m pytest tests/ -q

# 运行特定模块
python -m pytest tests/test_ocr_service.py -v
python -m pytest tests/test_local_paddleocr_inference.py -v
python -m pytest tests/test_local_paddleocr_routing.py -v
```

前端新增会话管理交互测试（SessionManager 组件）：

```bash
cd frontend

# 运行前端交互测试
npm run test:run
```

前端测试文件位置：
- `frontend/tests/unit/SessionManager.spec.ts`
- `frontend/src/components/SessionManager.vue`

属性测试覆盖的正确性属性包括：
- 内网地址校验（任意 URL → 正确分类内网/外网）
- OCR 降级与恢复（云端失败 → 自动本地、恢复后优先云端）
- 配置字段一致性（应用层 ↔ 服务层字段传递不丢失）
- PaddleOCR 结果拼接（任意文字行列表 → 换行拼接）
- 非法图像字节检测（任意非图像字节 → ValueError）
- 单模式路由隔离（LOCAL/REMOTE/CLOUD_VL → 仅调用对应后端）
- AUTO 模式降级（云端异常 → 自动切换本地）
- 本地推理超时（任意超时值 → TimeoutError）
- 批量处理摘要一致性、合并凭证借贷平衡、并发度限制等

## 技术栈

| 技术 | 用途 |
|------|------|
| Claude Agent SDK | AI 推理引擎 + 工具编排 |
| PaddleOCR / PaddleOCR-VL | 发票 OCR（云端 API + 本地推理双模式） |
| FastAPI | 异步 Web 服务 |
| MCP 协议 | 工具注册 + 凭证报文标准 |
| Pydantic | 数据模型校验 + 配置管理 |
| Hypothesis | 属性测试框架 |
| Vue3 + Pinia | 前端框架 |
| numpy + OpenCV | 本地图像解码 |

## 设计文档

详细的需求、设计和实施计划见 `.kiro/specs/` 目录：

| Spec | 内容 |
|------|------|
| `finance-agent-architecture-upgrade/` | 系统架构升级：12 项需求、25 个正确性属性、19 个实施任务 |
| `local-paddleocr-fallback/` | 本地 PaddleOCR 回退：8 项需求、7 个正确性属性、9 个实施任务 |
| `image-upload-ocr-fix/` | 图片上传 OCR 修复：Bug 条件分析 + 保持性验证 |

## 许可证

内部项目，仅限企业内部使用。

## 新增说明：统一外部提交通道（Submission Gateway）

为了支持后续对接账务系统、OA系统等多通道提交，后端新增统一提交抽象层：
- `extensions/submission_gateway.py` 定义 `SubmissionGateway` 接口
- 当前已实现 `OASubmissionGateway`（复用现有 `OAConnector`）
- `main.py` 在确认凭证后统一走网关提交，并返回：
  - `submission_channel`：提交通道（如 `oa`）
  - `external_id`：外部系统返回编号（如审批单号）

对应 `config.yaml` 新增：

```yaml
submission:
  enabled: false          # 是否启用统一外部提交通道
  channel: "oa"          # 提交通道：oa（当前）/ accounting（预留）
  retry_count: 1          # 失败重试次数
  retry_backoff_ms: 300   # 重试间隔（毫秒）
```
