# 智慧大脑 Agent MVP - RAG 知识库使用说明

**状态**：✅ MVP 第一部分（文档摄入 → pgvector → 带来源问答）已落地
**日期**：2026-07-16
**作者**：服务器侧 Claude（自动排障 + 实施）

---

## 1. MVP 已落地的能力

### 后端 API（`agentops-api-1` 容器，端口 8000）

| 端点 | 方法 | 用途 |
|---|---|---|
| `POST /v4/knowledge/upload` | multipart | 上传 PDF/MD/TXT，自动解析 → chunk → embed → 写库 |
| `POST /v4/knowledge/search` | JSON | 检索 top-k chunks（含 source_page/line 引用） |
| `POST /v4/knowledge/answer` | JSON | 检索 + synthesis 占位文本（P6 LLM 未集成） |

### 数据库（Supabase Postgres 同库）

- 启用 pgvector 0.8.0
- 新增 2 张表 + 4 个索引（含 HNSW）：
  - `public.documents` (元数据)
  - `public.document_chunks` (chunks + 384 维向量)
- 不启用 RLS（生产化阶段再加）

### Embedding

- 模型：`BAAI/bge-small-en`（v1）—— fastembed 0.8.0 + ONNX
- 维度：384
- 缓存路径：`/app/.cache/fastembed/`（128MB）
- **决策调整**：原计划用 `bge-small-en-v1.5`，改用 v1，因为 v1.5 在 fastembed 里没有 GCS 备份源，HF api/models endpoint 不稳定（504）。维度都是 384，schema 无需改。

### 关键参数

| 参数 | 值 | 说明 |
|---|---|---|
| chunk_size | 512 tokens | tiktoken cl100k_base |
| chunk_overlap | 64 tokens (12.5%) | 滑窗 |
| 文档格式 | PDF / MD / TXT | PDF 按页切，MD/TXT 按段落 |
| embedding batch | 32 chunks | fastembed 批大小 |

---

## 2. 调用示例（curl）

### 上传文档

```bash
curl -X POST http://localhost:8000/v4/knowledge/upload \
  -F "project_id=f9505558-d67d-462f-b77e-6b9550458a2b" \
  -F "display_name=My Document" \
  -F "file=@/path/to/document.pdf"
```

响应：
```json
{
  "document_id": "0ce483f3-d291-452a-b382-162dca426a0f",
  "filename": "architecture.md",
  "chunk_count": 7,
  "status": "ready",
  "error": null
}
```

### 检索

```bash
curl -X POST http://localhost:8000/v4/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "f9505558-d67d-462f-b77e-6b9550458a2b",
    "query": "HNSW 索引参数",
    "k": 3
  }'
```

响应：
```json
{
  "query": "HNSW 索引参数",
  "hits": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "document_name": "architecture.md",
      "content": "...",
      "source_page": null,
      "source_line": 18,
      "chunk_index": 4,
      "score": 0.971
    }
  ]
}
```

### 问答（合成 stub）

```bash
curl -X POST http://localhost:8000/v4/knowledge/answer \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "f9505558-d67d-462f-b77e-6b9550458a2b",
    "query": "如何提升检索性能",
    "k": 2
  }'
```

响应：
```json
{
  "query": "如何提升检索性能",
  "hits": [...],
  "synthesis": "Retrieved 2 relevant chunks for: \"如何提升检索性能\".\nSources: [1] architecture.md; [2] faq.txt\n\nTop match (score=0.986): ## 性能指标..."
}
```

---

## 3. 项目文件清单

### 新建文件

| 路径 | 行数 | 说明 |
|---|---|---|
| `/app/agentops/rag/embed.py` | 48 | fastembed 薄封装 |
| `/app/agentops/rag/parsers.py` | 55 | PDF/MD/TXT 解析 |
| `/app/agentops/rag/chunker.py` | 70 | 512/64 token 滑窗 |
| `/app/agentops/rag/db.py` | 95 | SQLAlchemy ORM (本地 _Base 隔离) |
| `/app/agentops/rag/ingest.py` | 120 | 主流程 7 步 pipeline |
| `/app/agentops/rag/search.py` | 67 | pgvector cosine + project 过滤 |
| `/app/agentops/api/routes/v4/knowledge.py` | 156 | 3 个 HTTP 端点 |

### 修改文件

| 路径 | 改动 |
|---|---|
| `/app/agentops/api/routes/v4/__init__.py` | +2 行（import + include_router） |
| `/app/.venv/lib/python3.12/site-packages/` | +5 包（fastembed, pypdf, pgvector, tiktoken 已有, python-multipart） |
| Supabase DB | +1 扩展 (vector) +2 表 +4 索引 |

### 备份文件（容器内 `/app/.bak/`）

所有改动前的文件都做了带时间戳的备份。

---

## 4. 决策日志

| # | 决策 | 理由 |
|---|---|---|
| D1 | embedding 模型 | fastembed + BAAI/bge-small-en (v1) —— 无外网 + 离线可用 |
| D2 | 文档格式 | PDF + MD + TXT 起步 |
| D3 | chunk 大小 | 512 token / 64 overlap（业界标准） |
| D4 | 存储后端 | pgvector（Supabase 同库，不引入新基础设施） |
| D5 | 摄入触发 | HTTP API + (计划) Dashboard 上传 |
| D6 | 多租户 | 挂到 projects 表（已有） |
| D7 | 鉴权 | MVP 阶段无（project_id 是信任边界） |
| D8 | 模型版本 | v1 而非 v1.5（v1.5 无 GCS 备份，HF api/models 不稳定） |

---

## 5. 已知限制与未来工作

### 限制（影响范围）

1. **无鉴权** —— 任何人知道 project_id 都能上传/检索。生产化前必须加。
2. **检索区分度低** —— bge-small 384 维对中英文混合 query 区分能力有限（top-3 score 经常都 0.93+）。
3. **无 LLM 答案合成** —— `/answer` 返回的是模板拼接，不是 LLM 生成的连贯答案。
4. **RLS 未启用** —— 数据库层面没有跨项目隔离，全靠应用层 project_id 校验。
5. **同步摄入** —— `/upload` 是同步阻塞；大文档会占请求线程。

### 未来优化项（P8+）

| 优化 | 预期收益 | 工作量 |
|---|---|---|
| 换 bge-base (768 维) 或加 reranker (bge-reranker-base) | 检索区分度显著提升 | 1 天 |
| 接本地 LLM（Ollama + qwen2.5 7B） | 真正 LLM 答案合成 | 2-3 天 |
| 加 RLS + 鉴权 | 多租户安全 | 2-3 天 |
| 异步摄入（BackgroundTasks + 进度查询） | 大文档不阻塞 | 0.5 天 |
| Dashboard UI（Next.js page） | 端到端可视化 | 4-6 天 |
| 文档版本管理（chunk 重新嵌入时保留历史） | 文档更新场景 | 2 天 |
| 删除文档级联清理 + 软删除 | 数据治理 | 1 天 |

---

## 6. 回滚

```bash
# 1. 停止 + 删除容器（保留镜像）
docker stop agentops-api-1
# 2. 恢复 .py 备份（容器内 /app/.bak/）
docker exec agentops-api-1 sh -c '
  cp /app/.bak/middleware.py.before-fix.20260716-080852 /app/agentops/common/middleware.py
  cp /app/.bak/auth_exceptions.py.before-fix2.* /app/agentops/auth/exceptions.py
  cp /app/.bak/auth_views.py.before-fix2.* /app/agentops/auth/views.py
  cp /app/.bak/api_app.py.before-fix2.* /app/agentops/api/app.py
  cp /app/.bak/v4__init__.py.before-knowledge.* /app/agentops/api/routes/v4/__init__.py
'
# 3. 回滚 schema（容器内）
docker exec supabase_db_database psql -U postgres -d postgres -f /tmp/rag_schema_p1_rollback.sql
# 4. 删除 RAG 模块
docker exec agentops-api-1 rm -rf /app/agentops/rag /app/agentops/api/routes/v4/knowledge.py
# 5. 重启
docker restart agentops-api-1
```

---

## 7. Dashboard UI 集成指南（给前端开发者）

> 注：本节是给本地侧前端开发者的指导，Dashboard 页面**未在本会话实施**。

### 需要新增的文件

```
app/(with-layout)/knowledge/
  page.tsx               # 主页面（三块 UI）
  _components/
    DocumentUpload.tsx   # 上传组件
    SearchBox.tsx        # 搜索框
    AnswerPanel.tsx      # 答案展示
    HitCard.tsx          # 单条 chunk 卡片
  hooks/
    useKnowledge.ts      # React Query hooks (upload/search/answer)
```

### API 调用示例（绕过鉴权）

MVP 阶段没鉴权，前端直接 fetch：

```typescript
// lib/api/knowledge.ts
const PROJECT_ID = process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID;

export async function uploadDocument(file: File) {
  const fd = new FormData();
  fd.append('project_id', PROJECT_ID!);
  fd.append('display_name', file.name);
  fd.append('file', file);
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v4/knowledge/upload`, {
    method: 'POST',
    body: fd,
  });
  return res.json();
}

export async function searchKnowledge(query: string, k = 5) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v4/knowledge/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: PROJECT_ID, query, k }),
  });
  return res.json();
}

export async function answerQuestion(query: string, k = 5) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v4/knowledge/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: PROJECT_ID, query, k }),
  });
  return res.json();
}
```

### UI 交互流程

1. **上传区**：拖拽 / 选择文件 → 调 `uploadDocument` → 显示"处理中" → 完成后刷新文档列表
2. **搜索区**：输入框 → 调 `searchKnowledge` → 列出 HitCard（content + source + score）
3. **问答区**：输入框 → 调 `answerQuestion` → 顶部展示 synthesis，底部折叠展示 hits

### 需要的 env

Dashboard `.env.local` 加：
```
NEXT_PUBLIC_DEFAULT_PROJECT_ID=f9505558-d67d-462f-b77e-6b9550458a2b
```

---

**完成时间**：2026-07-16 09:07
**总改动文件数**：7 新 + 2 改 + 1 schema 改
**累计 git 改动估算**：~700 行新代码 + 4 索引 + 2 表 + 5 pip 包