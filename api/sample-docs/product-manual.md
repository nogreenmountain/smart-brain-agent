# 智慧大脑 Agent 产品手册（完整版）

## 第一章：安装与部署

智慧大脑 Agent 依赖 Docker Compose 一键启动。需要的最低硬件配置：
- CPU: 4 核
- 内存: 8 GB
- 磁盘: 50 GB 可用空间
- 操作系统: Linux / macOS / Windows 11 with WSL2

启动命令：
```
docker compose up -d
```

## 第二章：用户管理

系统支持多用户协作。新用户注册后默认属于默认组织（Default Organization）。
管理员可以在设置页面邀请新成员、分配角色。

角色分为三种：
1. Owner：组织所有者，拥有所有权限
2. Admin：管理员，可以管理成员和项目，但不能删除组织
3. Member：普通成员，只能访问被授权的项目

## 第三章：项目管理

每个项目是一个独立的工作空间，包含：
- 项目元数据（名称、描述、环境）
- API Key（用于 SDK 上报数据）
- 知识库（智慧大脑特有功能）
- 追踪数据（来自 LLM Agent 的运行记录）

## 第四章：知识库

知识库是智慧大脑 Agent 的核心功能。用户可以上传 PDF、Markdown、TXT 三种格式的文档，
系统会自动切分、向量化、并存储到 PostgreSQL + pgvector 中。

检索时，用户输入查询，系统返回最相关的 Top-K 个文档片段，并附带来源（页码或行号）。

## 第五章：SDK 集成

智慧大脑 Agent 提供 Python SDK：

```python
from agent_sdk import AgentOps

ao = AgentOps(api_key="your-api-key")
ao.session.create(project_id="...")
```

SDK 会自动上报 Agent 的运行轨迹、LLM 调用、工具调用等到 ClickHouse。

## 第六章：API 参考

主要 API 端点：
- POST /auth/login - 用户登录
- GET /opsboard/projects - 获取项目列表
- POST /v4/knowledge/search - 知识库检索
- POST /v4/knowledge/answer - 带来源问答
- POST /v4/traces - 上报追踪数据

## 第七章：故障排查

登录失败：检查 API_DOMAIN、APP_DOMAIN、PROTOCOL 环境变量
向量检索慢：检查 HNSW 索引参数 m 和 ef_construction
文档摄入失败：查看 documents 表的 error_message 字段
