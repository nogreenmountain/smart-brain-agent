# AI Token 排行榜实施计划

## Goal

新增所有已登录用户可见的 `/leaderboard` 页面，用统一、可解释且不泄露对话详情的统计口径展示团队 AI Token 排行、多维构成和趋势。

## Locked decisions

- 用户已明确授权自主设计并直接实施，不再额外等待方案确认。
- 页面只公开按成员聚合的 Token、请求数、活跃天数、来源、应用和模型统计；不返回对话、Prompt、回复或工作日志。
- 默认显示最近 30 天，并支持最近 7 天、30 天、90 天及自定义日期，最大 366 天。
- CC Switch 对某成员覆盖完整日期范围时，以 `cc_switch_usage_daily` 官方汇总为准；未完整覆盖时使用已同步 `ai_chat_sessions` 的 CC Switch 会话统计；非 CC Switch 来源始终从会话汇总，并避免重复累计。
- 不引入新图表依赖；使用 SVG、CSS `conic-gradient` 和 Tailwind 构建美观、响应式图表。

## Phase 1 — Backend contract

- Files: `agentops_local/tests/test_ai_usage_leaderboard.py`, `agentops_local/api/routes/v4/ai_usage.py`
- Changes:
  - 新增 `/v4/ai-usage/leaderboard`。
  - 返回排行榜行、团队总览、每日趋势、来源构成、应用构成、Token 构成和模型排行。
  - 所有登录用户可调用；匿名仍由统一认证中间件拒绝。
  - 复用 CC Switch 官方 Token 语义和完整覆盖优先规则。
- Verify: 红测覆盖权限、去重、官方覆盖优先、排序和汇总一致性；项目测试通过。

## Phase 2 — Frontend page and navigation

- Files: `smartbrain-dashboard/lib/api.ts`, `components/Shell.tsx`, `components/Shell.test.tsx`, `app/(with-shell)/leaderboard/page.tsx`, `page.test.tsx`
- Changes:
  - 导航新增全员可见“AI 排行榜”。
  - 顶部总览指标、前三名领奖台、完整排行表。
  - 团队每日趋势 SVG 面积图。
  - AI 来源、应用类型、Token 构成三个环形图。
  - 模型排行横向条形图与成员效率指标。
  - 日期快捷筛选、自定义范围、加载/空状态/错误状态和移动端布局。
- Verify: 先红后绿；测试全员导航、日期请求、排序展示、图表无数据状态和隐私说明。

## Phase 3 — Release verification

- Files: `compose.server.override.yaml`, `AGENTS.md`
- Changes: 构建新 API/SmartBrain 镜像，重建 API/worker/SmartBrain，不重建 GPU 与 Wiki MCP。
- Verify:
  - Backend 完整测试、SmartBrain 全量测试、TypeScript、lint、production build。
  - 公网普通成员与管理员均可打开排行榜。
  - 核对 30 天团队总量与成员汇总之和一致。
  - 浏览器检查桌面/窄屏、控制台、图表和交互。
  - 清理临时账号、组织、Session、审计与标签页。

## Risks and controls

- 风险：CC Switch 日汇总与会话记录重复。控制：每个成员、每个请求范围只选择官方汇总或会话回退之一。
- 风险：公开排行榜越过详情隐私。控制：API DTO 不含记录和消息字段，页面明确只展示统计。
- 风险：历史用户无官方同步覆盖。控制：回退已同步会话并返回数据质量字段。
- 风险：图表大数值影响布局。控制：统一紧凑数字格式、百分比和响应式滚动。
