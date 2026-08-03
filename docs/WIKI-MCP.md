# Project Wiki MCP

Project Wiki MCP 让 Codex 按需读取已经发布的项目长期记忆，并把新经验提交到管理员待审批列表。它不会直接发布 Wiki，也不会把整个知识库一次性塞进模型上下文。

## 服务地址

- MCP: `http://192.168.1.40:8010/mcp`
- Health: `http://192.168.1.40:8010/health`
- Token 管理: `http://192.168.1.40:3002/wiki`

## 工具

- `list_wiki_projects`: 列出当前 Token 用户可访问的项目。
- `search_wiki`: 按关键词、类型、标签、更新时间和验证状态检索 Wiki。
- `get_page`: 读取完整 Markdown、来源、版本和关系。
- `get_related_nodes`: 遍历一到两层知识关系。
- `get_recent_updates`: 获取项目最近更新。
- `get_decision_records`: 查询决策和策略。
- `get_examples`: 查询失败案例、成功案例和复盘。
- `propose_memory`: 创建管理员待审批记忆，不直接发布。

## Codex 接入

推荐安装仓库内 `plugins/company-memory` 插件。也可以只注册 MCP：

```powershell
codex mcp add smartbrain-company-memory `
  --url http://192.168.1.40:8010/mcp `
  --bearer-token-env-var SMARTBRAIN_WIKI_MCP_TOKEN
```

Token 在 Wiki 页面创建后只显示一次。把它写入当前 Windows 用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable(
  "SMARTBRAIN_WIKI_MCP_TOKEN",
  "<token shown once by SmartBrain>",
  "User"
)
```

重新打开 Codex 任务后生效。不要把 Token 写入仓库、Skill、聊天记录或部署文档。

## 检索策略

Wiki 检索使用 PostgreSQL 关键词检索与 BGE-M3 `v2-hybrid` 融合。MCP 路径不启用 CrossEncoder 重排，以避免按需查询出现长时间等待；也不回退到旧 v1 本地模型。

优先读取 `verified`、最近更新、高置信度和高价值页面。`generated` 页面可作为线索，但不应被当作最终权威。多个页面冲突时，应展示冲突、版本和更新时间，再给出判断。

## 写入边界

只有带 `wiki:propose` scope 的 Token 可以调用 `propose_memory`。允许提交稳定、可复用的方法、流程、清单、决策、策略、案例和复盘；禁止提交密钥、个人信息、原始聊天转储、临时任务状态和无来源结论。

所有提案进入现有 `pending_review` 流程。管理员批准后才会发布为 Wiki 页面并进入后续检索。

## 部署

```powershell
docker build -f Dockerfile.api-workday `
  -t agentops-api-local:patched-2026-08-03-wiki-mcp .

docker compose -f compose.server.yaml -f compose.server.override.yaml build wiki-mcp

docker compose -f compose.server.yaml -f compose.server.override.yaml `
  up -d --force-recreate --no-deps api project-wiki-worker wiki-mcp
```

不要在没有 `compose.rag-gpu.override.yaml` 的情况下重建 RAG 模型服务，否则可能丢失 GTX 1080 CUDA 配置。
