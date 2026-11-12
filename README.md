# MinutesTrace

证据化 AI 会议纪要工作台。它把会议决策、行动项、风险与原始转写片段连接起来，并用 LangGraph 运行“审查 → 修订 → 再审查”流程。Agent 只生成候选修订；人工批准才会写入新的正式纪要版本。

## 已实现

- 会议、参会人、资料与处理状态管理
- 音视频异步转写（阿里云百炼 Paraformer）和 TXT/Markdown/SRT/VTT 本地导入
- Qwen 结构化纪要生成，无 Key 时使用确定性降级
- 片段级证据引用、说话人映射、文本修正
- LangGraph 可追踪审校、取消、人工批准/驳回
- Word/PDF 导出、任务和模型调用观测
- JWT 鉴权、管理员边界、幂等任务键和重启恢复
- Vue 3 响应式工作台与移动端布局

## 本地运行

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

另开终端启动任务工作进程与前端：

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m app.worker
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173/minutestrace/`，演示账号为 `demo / demo123456`，管理员为 `admin / demo123456`。生产环境必须在环境文件中修改密码和 JWT Secret。

## 配置

复制 `backend/.env.example` 为 `.env`。生产环境使用 MySQL；`MINUTESTRACE_LLM_API_KEY` 不得提交到仓库。接口契约见 `openapi.yaml`。

## 测试

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m pytest backend\tests -q
cd frontend
npm run build
```

## 部署结构

- Nginx 静态目录：`/opt/minutestrace/web`
- API：`127.0.0.1:18119`
- 对外前缀：`/minutestrace/`
- API 前缀：`/minutestrace/api/`
- systemd：`minutestrace-api.service`、`minutestrace-worker.service`
