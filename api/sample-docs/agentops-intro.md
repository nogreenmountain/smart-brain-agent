# AgentOps 智慧大脑简介

AgentOps 是一个面向 AI Agent 的可观测性与编排平台。智慧大脑 Agent 项目基于 AgentOps 的全栈基础设施构建，包含文档摄入、向量化存储和带来源问答能力。

## 核心能力

- 文档摄入：支持 PDF、Markdown、TXT 三种格式
- 向量化：使用本地 embedding 模型（bge-small），无需联网
- 向量检索：基于 pgvector + HNSW 索引，毫秒级响应
- 多租户：每个项目独立的知识库空间

## 架构

智慧大脑 Agent 复用 AgentOps 的 FastAPI + Next.js + Supabase + ClickHouse 全栈。文档摄入和检索作为新模块加入现有架构。

## 产品定价

智慧大脑 Agent 分为三个版本：
- 免费版：单项目，最多 100 文档
- 团队版：多项目，无限文档，月费 99 元
- 企业版：定制功能，按需报价
