# Smart Brain Agent 局域网部署包

这是“智慧大脑 Agent”的可迁移部署包，用于在内网快速部署一套研发部门知识库、持续更新的 Project Wiki、项目记忆、AI Monitor 和 AgentOps Trace 复盘环境。

## 包含什么

- `agentops_local/`：本项目后端补丁层，包含知识库、Project Wiki、项目管理、成员管理、AI Monitor、Workday 聚合等接口。
- `smartbrain-dashboard/`：中文智慧大脑前端，默认端口 `3002`。
- `api/`、`dashboard/`、`opentelemetry-collector/`：AgentOps 基础 API、Trace Dashboard、OTLP Collector 源码。
- `rag_services/`：BGE-M3 embedding 与 reranker 服务。
- `employee_telemetry/`：员工端通用安装包生成逻辑。
- `employee-deploy/universal/ai-monitor-universal/`：通用员工监控载荷模板。
- `employee_telemetry/windows_installer/`：单文件 EXE 图形安装器源码、构建脚本和无身份载荷。
- `smartbrain-dashboard/public/downloads/SmartBrain-AIMonitor-Setup-latest.exe`：员工自助安装成品。
- `supabase/migrations/`：数据库迁移。
- `deploy/lan/`：局域网部署脚本、初始化 SQL、部署说明。

## 不包含什么

- 不包含 `.env`、真实密钥、JWT、Minimax/OpenAI token。
- 不包含 Docker volume、ClickHouse/Postgres 数据文件、模型缓存。
- 不包含本机验证日志、旧个人员工包、临时运行缓存。

## 快速开始

详细步骤见：

- `deploy/lan/README-LAN-DEPLOY.md`
- `deploy/lan/REUSE-GUIDE.md`
- `docs/WIKI-MCP.md`

最短流程：

```powershell
cd smart-brain-agent
Copy-Item .env.lan.example .env
notepad .env

# 先启动/准备 Supabase 本地库，并执行 supabase/migrations
# 然后构建镜像并启动服务
powershell -ExecutionPolicy Bypass -File deploy/lan/Build-Images.ps1
powershell -ExecutionPolicy Bypass -File deploy/lan/Start-Lan.ps1
powershell -ExecutionPolicy Bypass -File deploy/lan/Initialize-Database.ps1
```

默认访问：

- 智慧大脑：`http://<服务器IP>:3002`
- Project Wiki：`http://<服务器IP>:3002/wiki`
- Wiki MCP：`http://<服务器IP>:8010/mcp`
- AgentOps Trace Dashboard：`http://<服务器IP>:3001`
- API：`http://<服务器IP>:8000`
- OTLP Collector：`http://<服务器IP>:4318`

员工端一键安装器可重新构建：

```powershell
powershell -ExecutionPolicy Bypass -File employee_telemetry\windows_installer\Build-Installer.ps1 `
  -OutputPath smartbrain-dashboard\public\downloads\SmartBrain-AIMonitor-Setup-latest.exe
```

构建脚本会下载并校验官方 CPython embeddable runtime；修改
`employee_telemetry\windows_installer\payload\manifest.json` 后可以替换服务器地址、
项目编号和默认邮箱域名。

默认初始化账号：

- 管理员：`hanshangbo` / `12345678`
- 测试成员：`test1` 到 `test12` / `123456`

正式给客户部署前，请立即修改管理员密码，并把 HTTP 升级为 HTTPS。
