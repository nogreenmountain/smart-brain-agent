# 复用方法说明

## 核心复用思路

智慧大脑是在 AgentOps 之上做的局域网研发知识工作台。迁移到另一家公司时，不要复制运行数据，而是复制这套结构：

1. AgentOps 原生 Trace/Span 可观测底座。
2. SmartBrain 中文 Dashboard。
3. 项目管理、成员管理、知识库台账、项目记忆审批流。
4. AI Monitor / Workday 聚合接口。
5. 员工端通用安装器，通过账号密码 enrollment 绑定员工身份。

## 新公司要替换的内容

- 服务器 IP / 域名。
- Supabase service role key / JWT secret。
- API session secret。
- LLM provider token 和 base url。
- 默认组织名称、默认项目名称。
- 员工账号、部门、项目成员关系。
- 是否启用 ChatGPT Web 内容采集，以及采集告知文案。

## 不建议复用的内容

- 当前公司的数据库数据。
- 当前公司的 ClickHouse Trace 数据。
- 当前员工 enrollment token。
- 当前机器 Docker image ID。
- 当前机器 `.env`。

## 推荐交付节奏

1. 服务器部署：先跑通 API、SmartBrain、ClickHouse、Collector。
2. 数据库初始化：创建管理员、部门、默认项目。
3. 小范围测试：1 台员工电脑安装 AI Monitor。
4. 真实任务测试：上传项目资料、审批成项目记忆、产生 AI 调用数据。
5. 安全加固：HTTPS、备份、密码策略、权限复核。
6. 扩大发放：生成统一员工包，按部门项目配置成员。

## 二次开发入口

- 后端业务接口：`agentops_local/api/routes/v4/`
- RAG/知识库：`agentops_local/rag/`
- 项目记忆：`agentops_local/project_memory/`
- Workday 聚合：`agentops_local/workday/`
- 前端页面：`smartbrain-dashboard/app/(with-shell)/`
- 前端 API 客户端：`smartbrain-dashboard/lib/api.ts`
- 员工端安装器：`employee_telemetry/`
