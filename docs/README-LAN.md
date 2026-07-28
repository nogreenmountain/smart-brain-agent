# 智慧大脑 Agent — 局域网部署说明

> 服务器：192.168.1.40（Windows Server / Windows 11 + Docker Desktop）
> 部署日期：2026-07-17

## 1. 谁能访问

局域网内任意电脑（同一网段 `192.168.0.0/16`）：
- ✅ **API**: `http://192.168.1.40:8000`
- ✅ **Dashboard**: `http://192.168.1.40:3001`
- ❌ Supabase / Postgres（仅服务器本机访问，外部被防火墙阻挡）

不在 LAN 的电脑：暂不支持（无公网暴露）。

## 2. 防火墙规则

```
AgentOps Allow API 8000 from LAN        (remoteip=192.168.0.0/16, TCP)
AgentOps Allow Dashboard 3001 from LAN   (remoteip=192.168.0.0/16, TCP)
AgentOps Block Supabase API              (localport=54321, TCP)
AgentOps Block Supabase DB               (localport=54322, TCP)
```

重启后规则**自动保留**（Windows Firewall 是持久的）。

如果需要重新应用防火墙规则（管理员 PowerShell）：

```powershell
netsh advfirewall firewall add rule name="AgentOps Allow API 8000 from LAN" dir=in action=allow protocol=TCP localport=8000 remoteip=192.168.0.0/16
netsh advfirewall firewall add rule name="AgentOps Allow Dashboard 3001 from LAN" dir=in action=allow protocol=TCP localport=3001 remoteip=192.168.0.0/16
netsh advfirewall firewall add rule name="AgentOps Block Supabase API" dir=in action=block protocol=TCP localport=54321
netsh advfirewall firewall add rule name="AgentOps Block Supabase DB" dir=in action=block protocol=TCP localport=54322
```

## 3. DNS 替代方案

如果同事记不住 IP，可以：
- 在路由器 DHCP 给服务器固定 IP（已经是 192.168.1.40）
- 在公司 DNS 加 `agentops.local → 192.168.1.40`
- 或者只发一条消息："192.168.1.40:3001"

## 4. 从 LAN 电脑验证

服务器上跑：

```bash
bash D:\AgentOpsServer\AgentOps\app\lan-diagnostics.sh
```

LAN 同事电脑手动跑（如果不想 bash）：

```cmd
ping 192.168.1.40
curl http://192.168.1.40:8000/health
curl http://192.168.1.40:3001/signin
```

期望：
- ping 通
- API `/health` 返回 `{"message":"Server Up"}`
- Dashboard `/signin` 200

## 5. HTTPS

当前**只有 HTTP**。生产化需要：
- 域名 + Let's Encrypt 证书
- 反向代理（nginx / Caddy）
- 配置改写

## 6. 备份策略

**当前没有自动备份**。建议管理员每周：

```powershell
# Postgres 备份
docker exec supabase_db_database pg_dump -U postgres postgres > backup_$(date +%Y%m%d).sql
```

恢复：
```bash
docker exec -i supabase_db_database psql -U postgres postgres < backup_20260717.sql
```

## 7. 监控

当前**没有外部监控**。建议接：
- 服务器 Windows 事件日志 → Sentry
- Docker stats → Prometheus
- 访问日志 → AgentOps 已有 `/v4/admin/audit-logs`

## 8. 故障排查

**同事浏览器打不开 192.168.1.40:3001**：
1. 服务器是否开机
2. Docker Desktop 是否启动
3. `docker ps` 看 dashboard 容器是否 Up
4. `curl http://localhost:3001/chat` 服务器本机测试
5. 防火墙规则是否还在 (`netsh advfirewall show rule name=all`)

**登录失败**：
- 用 testuser1@local.dev / TestUser123! 先验证系统本身
- 看 API 日志: `docker logs --tail 50 agentops-api-1`
- 401 = cookie 失效；403 = 权限不够；500 = 后端 bug

**答案质量差**：
- 看 `/admin-audit` 看 query 长度是否合理
- 检查文档 chunk 数量（在 `/documents` 页）

## 9. 联系服务器侧

如发现无法解决的问题：
- 截图当前页面 + 时间
- `docker ps` 输出
- `docker logs --tail 100 agentops-api-1` 输出

发给服务器侧 Claude 协助排查。