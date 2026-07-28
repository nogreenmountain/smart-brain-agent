# 智慧大脑 Agent — 管理员手册

> 给系统管理员的日常操作 + 排障参考。

## 1. 角色与权限矩阵

| 操作 | Owner | Admin | Developer | Viewer |
|---|---|---|---|---|
| 登录 | ✅ | ✅ | ✅ | ✅ |
| 检索 / 问答 | ✅ | ✅ | ✅ | ✅ |
| 上传 / 删除文档 | ✅ | ✅ | ✅ | ❌ |
| 添加项目成员 | ✅ | ✅ | ❌ | ❌ |
| 查看审计日志 | ✅ | ✅ | ❌ | ❌ |

权限粒度：**每个项目独立**。用户在不同项目可以是不同角色。

## 2. 创建用户

通过 GoTrue admin API（不用 UI）：

```python
# 在 agentops-api-1 容器内：
import os, urllib.request, json
url = "http://supabase_kong_database:8000/auth/v1/admin/users"
body = json.dumps({"email": "newuser@company.com", "password": "TempPass123!", "email_confirm": True}).encode()
req = urllib.request.Request(url, data=body, headers={
    "apikey": os.environ["SUPABASE_KEY"],
    "Authorization": f"Bearer {os.environ[\"SUPABASE_KEY\"]}",
    "Content-Type": "application/json",
}, method="POST")
print(urllib.request.urlopen(req).read())
```

或者用 Supabase Dashboard (https://supabase.com/dashboard)。

## 3. 创建项目

通过 API：

```bash
# 1. 拿 cookie (登录)
curl -X POST http://192.168.1.40:8000/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"email":"admin@company.com","password":"..."}'

# 2. 创建项目
curl -X POST http://192.168.1.40:8000/v4/projects \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=$(grep session_id cookies.txt | awk '{print $7}')" \
  -d '{"org_id":"<org-uuid>","name":"My Project","environment":"development"}'
```

**Note**: 创建者自动成为 project owner。

## 4. 加项目成员

```bash
curl -X POST http://192.168.1.40:8000/v4/projects/<project-id>/members \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=..." \
  -d '{"user_id":"<user-uuid>","role":"developer"}'
```

role 必须是 `owner` / `admin` / `developer` / `business_user`。

## 5. 删除项目

⚠️ 当前没有 DELETE 端点。需要直接 SQL：

```sql
DELETE FROM public.documents WHERE project_id = '<uuid>';
DELETE FROM public.project_members WHERE project_id = '<uuid>';
DELETE FROM public.projects WHERE id = '<uuid>';
```

文档 chunks 会通过 FK CASCADE 自动删除。

## 6. 看审计日志

```bash
# 通过 API
curl "http://192.168.1.40:8000/v4/admin/audit-logs?action=upload&limit=20" \
  -H "Cookie: session_id=..."

# 或直接查数据库
docker exec supabase_db_database psql -U postgres -d postgres -c "
SELECT id, (SELECT email FROM auth.users WHERE id=al.user_id) AS user, action, metadata, created_at
FROM audit_logs al
ORDER BY id DESC LIMIT 20;
"
```

## 7. 容器管理

```bash
# 看状态
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 重启 API
cd D:\AgentOpsServer\AgentOps\app
docker compose -f compose.server.yaml -f compose.server.override.yaml up -d api --force-recreate

# 重启 Dashboard
docker compose -f compose.server.yaml -f compose.server.override.yaml up -d dashboard

# 看 API 日志
docker logs --tail 100 agentops-api-1

# 重 build API（改 .py 后）
cd /tmp/ragpatch && docker build -t agentops-api-local:patched-2026-07-17 .

# 重 build Dashboard（改 .tsx 后）
cd D:\AgentOpsServer\AgentOps\app\dashboard && docker build -t agentops-dashboard-local:latest .
```

## 8. 备份

**当前每周手动跑**：

```powershell
# Postgres 备份（用 docker exec）
docker exec supabase_db_database pg_dump -U postgres postgres > D:\backup\pg_$(Get-Date -Format 'yyyyMMdd').sql

# 还原
Get-Content D:\backup\pg_20260717.sql | docker exec -i supabase_db_database psql -U postgres postgres
```

**自动化方案**：用 Windows 任务计划器每周日凌晨 3 点跑上面第一条命令。

## 9. 监控

**当前没有外部监控**。建议接入：

| 工具 | 用途 |
|---|---|
| Sentry | 前后端异常追踪（已配 Sentry DSN，UI 没接） |
| Prometheus + Grafana | Docker 资源监控 |
| UptimeRobot | HTTP 端点探活（公网 IP 才有意义） |

最简单：**手动每日看 audit_logs**。

## 10. 故障排查速查

| 症状 | 排查 |
|---|---|
| 同事浏览器打不开 | `docker ps` + 服务器本机 `curl localhost:3001/signin` |
| 登录 401 | cookie 失效 → 重登；或密码错 |
| 登录 500 | `docker logs agentops-api-1` 看 traceback |
| 检索没结果 | 文档 status 是否 ready？chunk 数 > 0？ |
| 答案质量差 | 检查 query 措辞；考虑换文档 / 改 chunk_size |
| API 启动失败 | `docker logs agentops-api-1` 看最后 30 行 |
| Dashboard build 失败 | Dockerfile 改了？清 `.next/cache` 后重 build |
| Firewall 问题 | `netsh advfirewall show rule name=all` 看规则还在 |
| Supabase 连不上 | `docker ps` 看 supabase_db_database 状态 |

## 11. 升级流程

### 修改后端（.py）

```bash
# 1. 改 D:\AgentOpsServer\AgentOps\app\agentops_local\...
# 2. rebuild + 重启
cd /tmp/ragpatch && docker build -t agentops-api-local:patched-2026-07-17 .
cd D:\AgentOpsServer\AgentOps\app
docker compose -f compose.server.yaml -f compose.server.override.yaml up -d api --force-recreate
```

### 修改前端（.tsx）

```bash
cd D:\AgentOpsServer\AgentOps\app\dashboard
docker build -t agentops-dashboard-local:latest .
cd ..
docker compose -f compose.server.yaml -f compose.server.override.yaml up -d dashboard
```

### 修改 schema（DB）

```bash
# 直接 psql 改（agentops_api container 内）
docker exec -i supabase_db_database psql -U postgres postgres

# 重要 schema 改前先备份
docker exec supabase_db_database pg_dump -U postgres postgres > backup_pre_change.sql
```

## 12. 联系

服务器侧 Claude 会自动跟踪 `E:\智慧大脑agent - 服务器端\` 下的进度文档。问题上报时附：
- 时间
- 复现步骤
- 相关错误截图
- `docker logs` 输出