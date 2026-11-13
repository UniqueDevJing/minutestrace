# MinutesTrace

MinutesTrace 是一个面向团队会议的证据化纪要工作台。它把录音、转写、会议结论、行动项和风险放在同一条可回溯链路中，让团队先确认事实，再发布正式纪要。

## 在线体验

- 产品入口：<http://114.215.186.113/minutestrace/>
- 演示账号：`demo / demo123456`
- 管理员账号：`admin / demo123456`
- 关联项目：[CareNexus](https://github.com/UniqueDevJing/CareNexus) —— 医疗就诊与运营工作台

## 产品能力

- 创建会议、维护参会人和会议资料
- 上传音视频，异步执行转写任务
- 导入 TXT、Markdown、SRT、VTT 文本
- 生成结构化纪要、行动项、决策与风险
- 每条结论关联原始转写片段和时间位置
- 说话人映射、文本修正与纪要版本管理
- Agent 自检缺项、矛盾和无证据结论
- 人工批准 / 驳回修订，Agent 不直接覆盖正式纪要
- Word / PDF 导出
- 任务状态、模型调用、延迟和失败原因观测

## 关键业务链路

```text
创建会议
  → 上传录音或会议文本
  → 异步转写与片段化
  → 生成结构化纪要
  → Agent 检查证据、缺项和风险
  → 人工批准修订
  → 发布并导出正式纪要
```

## 技术架构

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、SQLAlchemy、PyMySQL |
| Agent | LangGraph、结构化任务节点、人工审批边界 |
| 前端 | Vue 3、TypeScript、Vite、Vue Router |
| 模型 | 阿里云百炼 Qwen / Paraformer |
| 存储 | SQLite（开发）/ MySQL 8（生产） |
| 部署 | Nginx、systemd、独立 API 与 Worker |

## 本地运行

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

另开终端启动 Worker 与前端：

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m app.worker
cd frontend
npm install
npm run dev
```

本地入口：`http://127.0.0.1:5173/minutestrace/`

## 配置与部署

复制 `backend/.env.example` 为环境文件，并配置数据库、JWT Secret、上传目录和阿里云百炼 Key。生产部署文件位于 [`deploy/`](deploy/)，线上 API 前缀为 `/minutestrace/api/`。

## 测试

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m pytest backend\tests -q
cd frontend
npm run build
```

接口契约见 [`openapi.yaml`](openapi.yaml)，质量门禁记录见 [`QUALITY_GATE_REPORT.md`](QUALITY_GATE_REPORT.md)。
