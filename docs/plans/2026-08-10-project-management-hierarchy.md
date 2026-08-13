# 项目管理三级分级实施计划

## Goal

在项目管理页面形成“第一分级 → 第二分级（按需）→ 项目”的三级管理结构，同时保持现有项目权限、申请审批、资料、Wiki 和成员关系不变。

## Decisions locked

- 第一分级固定为：研发支撑、团队管理、产业侧、教学侧、科研侧。
- 研发支撑、团队管理可直接包含项目。
- 产业侧、教学侧、科研侧分别包含市场、业务两个第二分级，项目只能放在可承载项目的节点。
- 现有研发项目映射到研发支撑；现有市场项目映射到产业侧/市场；现有业务项目映射到产业侧/业务。
- 项目移交只更新 `projects.department_id`，不改变项目 ID、组织、成员、资料、Wiki 或历史数据。

## Phase 1 — 数据模型和后端契约

- Files: `supabase/migrations/20260810040000_add_project_management_hierarchy.sql`, `agentops_local/api/routes/v4/project_memory.py`, `agentops_local/api/routes/v4/projects.py`
- Changes: 为部门节点增加父级和项目承载能力；写入固定分级；后端只允许在项目承载节点创建、申请或移交项目；列表接口返回父级信息。
- Verify: 后端单元测试覆盖层级列表、非承载节点拒绝、叶子节点创建/申请/移交。

## Phase 2 — 项目管理页面

- Files: `smartbrain-dashboard/lib/api.ts`, `smartbrain-dashboard/app/(with-shell)/admin/page.tsx`, `smartbrain-dashboard/app/(with-shell)/admin/page.test.tsx`
- Changes: 增加第一/第二分级选择，项目作为第三级列表；创建、申请、审批展示和移交使用完整分类路径；移除页面上的自由创建部门入口。
- Verify: 前端测试覆盖无第二分级和有第二分级两条路径，以及跨分级移交。

## Phase 3 — 迁移、部署与验收

- Files: Compose/build artifacts and `AGENTS.md`
- Changes: 应用幂等迁移，构建 API/worker 与 SmartBrain 镜像，执行真实浏览器 E2E。
- Verify: 数据库分级和 27 个现有项目映射对账；完整测试、类型检查、lint、生产构建、API/公网健康和浏览器控制台检查。

## Risks

- `departments.name` 当前全局唯一，必须改成同一父级内唯一，才能允许三个“市场”和三个“业务”。
- 旧客户端仍提交 `research/marketing/business`，因此保留这三个 ID 并改变其层级语义，避免破坏已有外键与历史数据。
- 知识库和成员页仍使用扁平项目容器列表；部门接口默认只返回可承载项目的节点，项目管理页显式请求完整层级。
