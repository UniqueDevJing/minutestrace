# MinutesTrace 系统级质检与优化报告

## 范围与结论

检查对象为 FastAPI 后端、持久化任务 Worker、LangGraph 审校、SSE 事件流、文件上传/导出、管理员配置和 Vue 工作台。覆盖会议→资料→转写→说话人→纪要→Agent 审校→人工批准→导出的完整链路。

当前结论：**本地链路已通过，可进入预发布验收；生产仍需 MySQL、真实百炼 Key、Nginx 与多进程场景复测。**

## 优化优先级清单

| 编号 | 级别 | 问题/风险 | 修复状态 |
|---|---|---|---|
| MT-P0-01 | 致命 | 非管理员 dashboard 原始统计查询包含其他所有者数据 | 已修复：会议、审校、行动项、证据片段统计统一按 owner 过滤 |
| MT-P0-02 | 致命 | 同一幂等键并发创建任务可能触发唯一键 500 | 已修复：捕获 `IntegrityError`，返回已创建任务 |
| MT-P1-01 | 严重 | DB 提交失败后已落盘文件成为孤儿文件 | 已修复：提交异常 rollback 并删除最终文件 |
| MT-P1-02 | 严重 | stale worker 恢复逻辑会把所有 running AgentRun 改成 queued | 已修复：只恢复与过期 Job 关联的运行 |
| MT-P1-03 | 严重 | 会议详情页提交任务后不自动刷新，用户无法可靠观察状态 | 已修复：任务进行中每 2.5 秒轮询，卸载时清理定时器 |
| MT-P2-01 | 建议 | SSE ticket replay cache 仍为单进程内存结构，多 worker 不能共享 | 待后续：生产多副本时迁移 Redis/数据库票据存储 |
| MT-P2-02 | 建议 | `MinutesVersion(meeting_id, version)` 缺少数据库唯一约束 | 待后续：配套生产迁移脚本后增加约束 |

## 验证记录

- 后端：`PYTHONPATH=backend .venv\Scripts\python -m pytest -q`，7 项通过；`compileall` 通过。
- 前端：`npm run build` 通过，产物 JS gzip 约 61.5 KB。
- 依赖：当前生产依赖未发现 npm 审计漏洞；Python 依赖已锁定版本。

## 上线前人工门禁

1. 使用生产 MySQL 执行迁移/备份恢复演练，禁止 SQLite 作为生产库。
2. 注入随机 JWT Secret、非默认演示密码和百炼 Key，确认生产启动校验通过。
3. 运行两个 Worker 实例验证同一幂等键只产生一个 Job，并验证 stale recovery 不误改其他运行。
4. 实测 512 MB 边界、错误 MIME、断点重连、导出中文字体和对象级越权。
5. 若部署多副本，先完成 Redis/数据库 SSE ticket 共享，再开放横向扩容。
