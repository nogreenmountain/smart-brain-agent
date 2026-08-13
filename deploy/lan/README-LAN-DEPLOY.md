# 局域网部署手册

## 1. 服务器准备

推荐配置：

- Windows 10/11 或 Windows Server
- Docker Desktop + WSL2
- 16GB 内存以上，研发知识库建议 32GB
- 100GB 以上非 C 盘 Docker 数据盘
- 可选 GPU：NVIDIA GPU + WSL CUDA，RAG 模型服务可启用 GPU override

必须安装：

- Git
- Docker Desktop
- Node.js 20（仅本地调试前端需要）
- Python 3.12（仅运行辅助脚本需要）
- Supabase CLI，或一套可访问的 Supabase/Postgres 服务

## 2. 初始化配置

```powershell
cd smart-brain-agent
powershell -ExecutionPolicy Bypass -File deploy/lan/New-LanEnv.ps1 -ServerIP 192.168.1.40
notepad .env
```

需要重点确认：

- `LAN_SERVER_IP`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`
- `JWT_SECRET_KEY`
- `AUTH_COOKIE_SECRET`
- `ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_BASE_URL`

`New-LanEnv.ps1` 只自动生成本项目的 JWT/Cookie 随机密钥。Supabase JWT Secret 和 Service Role Key 必须从目标 Supabase 实例复制，脚本不会伪造可用值。

如果使用 Supabase CLI，本地启动后可通过 `supabase status` 查看 anon/service role key。

## 3. 准备数据库

推荐方式：

```powershell
supabase start
supabase db reset
```

如果不是全新数据库，不要执行 reset。请改用你们自己的迁移流程执行 `supabase/migrations`。

迁移必须按文件名顺序执行到 `20260813000000_add_shared_cc_switch_sessions.sql`。已有数据库升级请先阅读 `UPGRADE-2026-08-13.md` 并完成备份。

迁移完成后，可选择初始化演示组织、项目和账号：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/lan/Initialize-Database.ps1
```

默认账号：

- 管理员：`hanshangbo` / `12345678`
- 测试员工：`test1` 到 `test12` / `123456`

该初始化脚本只用于演示/验收。正式客户环境应使用自有组织、账号和项目数据，且项目必须挂在第二分级；默认演示项目挂在 `研发支撑 / 直属分级`。

## 4. 构建镜像

```powershell
powershell -ExecutionPolicy Bypass -File deploy/lan/Build-Images.ps1
```

该脚本会构建：

- AgentOps API 基座镜像
- SmartBrain patched API 镜像
- AgentOps Trace Dashboard
- SmartBrain 中文 Dashboard
- OTLP Collector
- RAG embedding / reranker 服务

## 5. 启动服务

```powershell
powershell -ExecutionPolicy Bypass -File deploy/lan/Start-Lan.ps1
```

访问：

- 智慧大脑：`http://<服务器IP>:3002`
- AgentOps Trace Dashboard：`http://<服务器IP>:3001`
- API Health：`http://<服务器IP>:8000/health`
- OTLP HTTP：`http://<服务器IP>:4318`
- Wiki MCP：`http://<服务器IP>:8010/mcp`

## 6. 生成员工端安装包

先确认 API 正在运行，并且默认项目存在：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/lan/New-EmployeeBundle.ps1 `
  -ProjectId "f9505558-d67d-462f-b77e-6b9550458a2b" `
  -ServerIP "192.168.1.40"
```

输出目录：

```text
employee-deploy/universal/ai-workday-universal
```

把这个目录发给员工。员工首次运行安装器时输入智慧大脑账号密码即可完成绑定。

## 7. 验收清单

- 用 `hanshangbo/12345678` 登录 `http://<服务器IP>:3002`
- 成员管理能看到 `test1` 到 `test12`
- 项目管理能看到默认项目
- 项目管理显示固定三级分类，第一分级自动拥有“直属分级”
- 上传资料包含项目原始资料、会议记录、GitHub 仓库页签
- 智慧 Wiki 包含项目 Wiki、成员 Wiki 页签
- AI 工作台包含工作记录、团队排行、工作日志、设备与同步页签
- 普通成员不能删除资料；管理员可以删除资料
- AI 工作日页面可查看 Workday 汇总
- 员工端安装后，CC Switch / ChatGPT Web 监控数据能进入 AI Monitor
- AgentOps Trace Dashboard 能按 trace id 打开复盘

## 8. 正式上线注意事项

- 修改默认管理员密码。
- 开启 HTTPS，HTTP 只适合受控内网试运行。
- 不要把 `.env`、数据库 volume、员工已签发 token 推到 Git。
- 不要复制生产 `production-backups/`、Docker 网络元数据恢复文件或 `.next*` 构建残留。
- Docker Desktop 数据目录建议迁到 D/E 盘。
- 客户环境如果有合规要求，先确认聊天内容采集边界和员工告知流程。
