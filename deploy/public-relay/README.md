# SmartBrain 公网 IP 中转部署

当前部署使用固定公网 IP `39.105.79.0`、Let’s Encrypt 公开可信 IP 证书、Nginx 和受限反向 SSH 隧道。业务与 GPU 服务继续运行在本地服务器，云服务器只负责 TLS 终止和流量中转。

## 公网入口

- 智慧大脑：`https://39.105.79.0/`
- API：与网页同源，通过 `/auth/*`、`/v4/*` 和 `/health` 转发
- Project Wiki MCP：`https://39.105.79.0/mcp`
- OTLP HTTP：`https://39.105.79.0/v1/traces`
- AgentOps Trace：`https://39.105.79.0/traces`

日常使用只依赖公网 TCP `443`。TCP `80` 用于 HTTPS 跳转和 Let’s Encrypt HTTP-01 自动续期；SSH 管理使用 TCP `22`。云平台无需额外放开 3001、3002、4318、8000、8010。

## 首次在新 Windows 电脑使用

无需下载或安装私有根证书，直接打开 `https://39.105.79.0/` 并登录。浏览器、Codex MCP、CC Switch 和标准 OTLP 客户端都应直接信任当前证书。

AI Monitor `2026-08-06-r14-public-ip-https` 仍内嵌旧私有根证书以兼容已经发放的安装包；该证书不再是连接公网服务的必要条件。

## 本地反向隧道

隧道容器只允许向云端回环地址开放固定端口，不能登录云服务器 Shell：

| 云端回环端口 | 本地服务 |
|---|---|
| 13002 | SmartBrain 3002 |
| 18000 | API 8000 |
| 18010 | Wiki MCP 8010 |
| 13001 | AgentOps Dashboard 3001 |
| 14318 | OTLP HTTP 4318 |

启动与验证：

```powershell
docker compose -f deploy/public-relay/docker-compose.reverse-tunnel.yaml up -d --build
powershell -ExecutionPolicy Bypass -File deploy/public-relay/Test-ReverseTunnelConfig.ps1
```

私钥必须只保存在本机受限目录中，不能复制到仓库。Compose 中的密钥挂载路径需要按实际 Windows 用户目录调整。

## 云端 Nginx

公开 IP 证书与私钥由 Certbot 管理：

- `/etc/letsencrypt/live/39.105.79.0/fullchain.pem`
- `/etc/letsencrypt/live/39.105.79.0/privkey.pem`
- Webroot：`/var/www/letsencrypt`
- 续期 reload hook：`/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`

启用配置：

```bash
sudo install -o root -g root -m 644 smartbrain-ip.conf /etc/nginx/conf.d/smartbrain-ip.conf
sudo nginx -t
sudo systemctl reload nginx
```

Let’s Encrypt IP 证书有效期为 160 小时。云服务器使用 Certbot 5.7 和 `snap.certbot.renew.timer` 自动续期，续期配置必须保留 `preferred_profile = shortlived`、`authenticator = webroot`，成功续期后自动检查并 reload Nginx。任何私钥都不得复制到仓库。

续期验证：

```bash
sudo certbot renew --cert-name 39.105.79.0 --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

## 应用环境

从 `.env.public-relay.example` 合并公网变量到本机 `.env`。轮换网页会话密钥时：

1. 把旧 `AUTH_COOKIE_SECRET` 保存为独立的 `WIKI_MCP_TOKEN_SECRET`；
2. 再生成新的 `AUTH_COOKIE_SECRET`；
3. 重建或重启 API 与 Wiki MCP。

这样会让旧网页 Session 失效，但不会让已发放的 MCP Token 失效。任何真实密钥、Token、Cookie 和私钥都不得提交。

## 验证脚本

- `scripts/Test-PublicRelayLogin.ps1`：临时创建高强度密码测试用户，验证登录/CORS/全局读取后自动删除。
- `scripts/Test-PublicRelayUpload.ps1`：验证资料敏感信息预检上传并清理所有测试数据。
- `scripts/Test-PublicRelayMcp.ps1`：使用当前用户环境变量中的 MCP Token 验证初始化和工具列表。
- `scripts/Test-PublicRelayOtlp.ps1`：通过公网 HTTPS 写入测试 Span，验证 ClickHouse 后同步删除。
- `scripts/Test-PublicRelayInstaller.ps1`：下载最新版 EXE，核对哈希、端点和内嵌根证书。

这些脚本不会输出服务端密钥、MCP Token、登录密码或会话 Cookie。
