# Smart Brain Agent 局域网部署包

这是“智慧大脑 Agent”的可迁移部署包，用于部署项目知识库、持续更新的智慧 Wiki（项目 Wiki / 成员 Wiki）、统一上传工作区、AI 工作台、AI Monitor 和 AgentOps Trace 复盘环境。

当前代码基线同步自 2026-08-13 生产验收版本。生产数据库、容器卷、机器专用镜像 ID 和真实凭据不属于本仓库。

## 包含什么

- `agentops_local/`：本项目后端补丁层，包含知识库、智慧 Wiki、会议记录、三级项目分类、知识资产迁移、成员管理、AI Monitor、Token 排行榜与工作日志等接口。
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
- `deploy/lan/UPGRADE-2026-08-13.md`
- `docs/WIKI-MCP.md`

最短流程：

```powershell
cd smart-brain-agent
# 先启动/准备 Supabase 本地库，并按文件名顺序执行 supabase/migrations
# 再生成本机 .env、构建镜像并启动服务
powershell -ExecutionPolicy Bypass -File deploy/lan/New-LanEnv.ps1 -ServerIP 192.168.1.40
notepad .env
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

当前产品口径：侧栏提供“智慧 Wiki”“上传资料”“AI 工作台”等统一入口；项目分类固定为“第一分级 → 第二分级 → 项目”，每个第一分级自动带一个不可单独维护的“直属分级”。所有上传、审批、删除、知识资产迁移和项目管理写操作仍按项目角色授权。

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

正式给客户部署前，请立即修改管理员密码、测试账号密码和 ClickHouse 默认密码，并把 HTTP 升级为 HTTPS。初始化 SQL 只适用于演示/验收环境；正式环境应替换为客户自己的组织、成员和项目数据。
