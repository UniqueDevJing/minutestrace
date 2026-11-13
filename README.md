# MinutesTrace

MinutesTrace 是一套会议资料与纪要协同工作台。它把录音、文本、转写片段、会议决定和行动项放在同一个页面中，所有正式结论都能回到原始材料，适合需要留痕、复核和持续跟进的团队会议。

## 解决的问题

- 录音和会议资料分散，结束后很难找到原文依据。
- 纪要中的负责人、截止时间和决定容易遗漏。
- 自动生成的内容如果没有人工复核，不适合直接作为正式记录。
- 会议结束后，行动项缺少状态、责任人和后续跟踪入口。

## 功能模块

### 会议空间

- 创建会议，填写主题、时间、地点和参会人。
- 查看会议状态、资料数量、处理进度和最近活动。
- 会议之间相互隔离，成员只能访问自己有权限的会议。

### 资料与转写

- 上传音频或视频，后台异步处理转写任务。
- 导入 TXT、Markdown、SRT、VTT 等文本资料。
- 保留说话人、时间戳和原始片段，支持定位到具体发言。
- 支持文本修正和说话人映射，修改记录可追踪。

### 纪要与行动项

- 生成会议摘要、讨论要点、决定、风险和行动项。
- 为每条结论保存来源片段和证据位置。
- 编辑负责人、截止时间、优先级和完成状态。
- 会议版本独立保存，避免草稿覆盖已经发布的正式纪要。

### 复核与发布

- 自动检查缺少负责人、截止时间、证据或互相矛盾的内容。
- 复核人可以接受、修改或驳回建议。
- 未经过人工批准的草稿不能导出为正式纪要。
- 支持 Word、PDF 导出，并保留导出时的版本号。

### 运行观测

- 查看转写、整理、检查和导出任务的状态。
- 查看模型调用次数、耗时、失败原因和降级结果。
- 失败任务可重试，任务状态不会因为刷新页面而丢失。

## 业务流程

```text
创建会议
    → 上传录音或导入文本
    → 后台转写并切分发言
    → 整理摘要、决定和行动项
    → 检查证据、缺项和冲突
    → 人工复核并形成正式版本
    → 发布、导出和持续跟踪
```

系统把“建议内容”和“正式记录”分开保存。整理过程出现异常时，原始资料和已确认版本仍然保留，不会被失败任务覆盖。

## 技术组成

| 部分 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、SQLAlchemy、PyMySQL |
| 任务处理 | 独立 Worker、任务状态机、SSE 进度推送 |
| 前端 | Vue 3、TypeScript、Vite、Vue Router |
| 模型接口 | 阿里云百炼兼容接口，支持文本处理和语音转写 |
| 数据库 | SQLite（开发）/ MySQL 8（生产） |
| 部署 | Nginx、systemd、独立 API 与 Worker |

## 目录结构

```text
MinutesTrace/
├─ backend/app/        # API、数据模型、任务处理和业务规则
├─ backend/tests/      # 接口和业务测试
├─ frontend/           # Vue 前端
├─ deploy/             # systemd、Nginx 和服务器安装脚本
├─ openapi.yaml        # 接口契约
└─ QUALITY_GATE_REPORT.md
```

## 本地运行

### 安装后端依赖

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
```

### 启动 API

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

### 启动 Worker 和前端

另开终端执行：

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m app.worker
```

再开一个终端：

```powershell
cd frontend
npm install
npm run dev
```

默认入口：`http://127.0.0.1:5173/minutestrace/`

## 配置

复制 `backend/.env.example` 为本地环境文件，至少配置：

- 数据库连接地址。
- JWT Secret。
- 文件存储目录。
- 模型接口地址和密钥。
- 上传大小、任务超时和并发限制。

正式环境的账号、密码和密钥通过服务器环境变量注入，不写入 README、测试数据或提交记录。

## 接口与部署

- 接口契约：[`openapi.yaml`](openapi.yaml)
- 部署文件：[`deploy/`](deploy/)
- 生产 API 前缀：`/minutestrace/api/`
- 前端路径：`/minutestrace/`

部署时需要同时运行 API 服务、Worker 和 Nginx。只启动前端不会处理上传和异步任务。

## 测试

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m pytest backend\tests -q

cd frontend
npm run build
```

质量检查记录见 [`QUALITY_GATE_REPORT.md`](QUALITY_GATE_REPORT.md)。

## 相关项目

- [CareNexus](https://github.com/UniqueDevJing/CareNexus/)：医院就诊与运营协同系统。
