# MinutesTrace｜基于 FastAPI + LangGraph 的智能会议助手

MinutesTrace 是一套面向团队会议的资料、转写、纪要和行动项工作台。它把“原始资料—转写片段—纪要结论—行动项—人工确认”串成一条可回溯的数据链，适合需要留痕、复核和持续跟进的研发、产品与客户成功团队。

## 在线体验（仅演示）

- 体验地址：<http://114.215.186.113/minutestrace/>
- 普通成员：`demo` / `demo123456`
- 管理员：`admin` / `demo123456`

以上账号仅用于公开演示，不包含真实会议资料或生产权限。当前服务器显式开启 `MINUTESTRACE_PUBLIC_DEMO=true`；普通生产环境保持 `false`，并通过环境变量注入独立账号、数据库、JWT Secret 和阿里云百炼密钥。

## 项目亮点

- **资料到结论的证据链**：每条议题、决定、风险和行动项都可回到具体转写片段和时间戳。
- **异步任务状态机**：上传、转写、纪要生成和 Agent 自检独立排队，支持进度、重试、失败原因和重启恢复。
- **人工确认边界**：Agent 只能生成草稿和修订建议；未经过人工批准的版本不能作为正式纪要导出。
- **版本与行动项独立管理**：纪要版本不会覆盖正式记录，行动项支持负责人、截止时间、状态和后续跟踪。
- **面向运营的观测**：记录任务耗时、模型调用、Token、失败原因、Agent 节点和运行状态，便于定位线上问题。
- **角色与数据隔离**：普通成员只能访问自己负责的会议，管理员拥有组织、模型、提示词和全局观测权限。

## 完整业务流程

```text
创建会议
    → 上传音视频或导入 TXT / Markdown / SRT / VTT
    → Worker 异步转写并保留说话人与时间戳
    → 生成摘要、议题、决定、风险和行动项
    → Agent 检查证据、缺项与冲突
    → 人工确认并形成正式版本
    → Word / PDF 导出与行动项跟踪
```

## 功能模块

| 模块 | 能力 |
| --- | --- |
| 会议空间 | 创建、状态管理、参会人、议程、会议详情和权限隔离 |
| 资料中心 | 音视频与文本导入、文件校验、资料归属和转写入口 |
| 转写任务 | 异步处理、分段、说话人、时间戳、重试与错误记录 |
| 纪要工作台 | 摘要、议题、决定、风险、待确认和证据跳转 |
| Agent 自检 | 完整性、可落实性、冲突检查、修订建议和人工审批 |
| 行动项 | 负责人、截止时间、状态、来源片段和持续跟进 |
| 运行观测 | 任务、模型调用、Token、耗时、失败原因和节点轨迹 |
| 系统配置 | 模型配置、Prompt 版本、部门和员工账号 |

## 技术与架构

| 层次 | 技术 |
| --- | --- |
| API | Python 3.12、FastAPI、Pydantic、SQLAlchemy |
| Agent / 模型 | LangGraph、阿里云百炼兼容接口、SSE |
| 任务处理 | 独立 Worker、幂等键、重试、心跳和僵尸任务恢复 |
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Lucide |
| 数据 | SQLite（开发）、MySQL 8（生产） |
| 部署 | Nginx、systemd、独立 API 与 Worker |

## 目录结构

```text
MinutesTrace/
├─ backend/app/        # API、模型、业务状态和任务处理
├─ backend/tests/      # 接口、权限、幂等和状态流转测试
├─ frontend/           # Vue 工作台、数据总览和角色模块
├─ deploy/             # systemd、Nginx、生产配置与安装脚本
├─ openapi.yaml        # 接口契约
└─ QUALITY_GATE_REPORT.md
```

## 本地运行

### 后端与 Worker

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

另开终端运行 Worker：

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m app.worker
```

### 前端

```powershell
cd frontend
npm install
npm run dev
```

默认入口：<http://127.0.0.1:5173/minutestrace/>。

## 配置与生产边界

复制 `backend/.env.example` 为本地环境文件，配置数据库、JWT Secret、文件存储、上传限制、任务超时和模型接口。普通生产环境拒绝 SQLite、默认 JWT Secret 和默认演示密码；公开演示模式只在明确开启 `MINUTESTRACE_PUBLIC_DEMO=true` 时创建演示身份与演示数据。账号、密钥和真实资料不会写入仓库。

生产入口为 `/minutestrace/`，API 前缀为 `/minutestrace/api/`。部署时必须同时运行 API、Worker 和 Nginx，具体文件见 [`deploy/`](deploy/)。

## 验证命令

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m pytest backend\tests -q

cd frontend
npm run build
```

质量检查记录见 [`QUALITY_GATE_REPORT.md`](QUALITY_GATE_REPORT.md)。

## 相关项目

- [CareNexus](https://github.com/UniqueDevJing/CareNexus/)：基于 LangChain4j + Spring Boot 的智能分诊就医系统。
