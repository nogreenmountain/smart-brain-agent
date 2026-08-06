# SmartBrain 公网 IP 中转部署

当前部署使用固定公网 IP `39.105.79.0`、私有根 CA、Nginx 和受限反向 SSH 隧道。业务与 GPU 服务继续运行在本地服务器，云服务器只负责 TLS 终止和流量中转。

## 公网入口

- 智慧大脑：`https://39.105.79.0/`
- API：与网页同源，通过 `/auth/*`、`/v4/*` 和 `/health` 转发
- Project Wiki MCP：`https://39.105.79.0/mcp`
- OTLP HTTP：`https://39.105.79.0/v1/traces`
- AgentOps Trace：`https://39.105.79.0/traces`
- 根证书下载：`http://39.105.79.0/smartbrain-root-ca.crt`

日常使用只依赖公网 TCP `443`。TCP `80` 仅用于 HTTPS 跳转和首次下载公开的根证书；SSH 管理使用 TCP `22`。云平台无需额外放开 3001、3002、4318、8000、8010。

## 首次在新 Windows 电脑使用

1. 下载 `http://39.105.79.0/smartbrain-root-ca.crt`。
2. 核对根证书 SHA-256 指纹：
   `2F:BF:D7:AB:D1:29:B3:06:56:7D:9B:74:E8:32:8D:89:F1:DD:8D:40:B7:D1:09:9F:23:C8:90:B0:B9:9C:B2:56`。
3. 将证书安装到“当前用户”的“受信任的根证书颁发机构”。也可以执行：

   ```powershell
   certutil -user -addstore Root .\smartbrain-root-ca.crt
   ```

4. 打开 `https://39.105.79.0/` 并重新登录。

AI Monitor `2026-08-06-r14-public-ip-https` 及以后版本已内嵌同一根证书，会在当前用户证书库中幂等安装，无需管理员权限。

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

证书与私钥安装在云服务器：

- `/etc/nginx/smartbrain-pki/server.crt`
- `/etc/nginx/smartbrain-pki/server.key`
- `/etc/nginx/smartbrain-pki/root-ca.crt`

启用配置：

```bash
sudo install -o root -g root -m 644 smartbrain-ip.conf /etc/nginx/conf.d/smartbrain-ip.conf
sudo nginx -t
sudo systemctl reload nginx
```

`server.key` 必须保持 `root:root 600`，不得放入仓库。根证书和服务端证书是公开材料，可设为 `644`。

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
