智慧大脑 AI Monitor 统一安装包

适用范围

本安装包发给所有研发员工使用，不再区分 test1、test2 或个人专属包。

它包含三类入口：

1. CC Switch / Claude Code / Codex 遥测配置
2. ChatGPT 网页版监控插件和受监控浏览器快捷方式
3. 智慧大脑网页安装检测入口

网页入口

智慧大脑：
http://192.168.1.40:3002

安装检测页：
http://192.168.1.40:3002/monitor/setup

员工安装步骤

1. 打开智慧大脑网页登录账号。
2. 进入“AI Monitor”页面，点击“下载安装包”。
3. 解压下载的 zip 到本机任意非系统目录。
4. 从系统托盘彻底退出 CC Switch。
5. 关闭正在运行的 Edge / Chrome 浏览器。
6. 在解压目录运行：

   powershell -ExecutionPolicy Bypass -File .\Install-AIMonitor.ps1

7. 按提示输入智慧大脑用户名和密码。短用户名会自动补全 @local.dev。
8. 安装成功后重新打开 CC Switch，分别切换一次 Claude 和 Codex 当前供应商。
9. 使用桌面上的“SmartBrain Monitor Setup - Edge”或“SmartBrain Monitor Setup - Chrome”回到检测页确认状态。
10. 使用桌面上的“ChatGPT Monitored - Edge”或“ChatGPT Monitored - Chrome”打开 ChatGPT 网页版。
11. 在 ChatGPT 页面右下角的“智慧大脑 AI Monitor”面板里登录智慧大脑，并填写任务 ID / 任务标题。

能监控什么

- CC Switch 转接的 Claude Code / Codex 调用
- ChatGPT 网页版个人账号聊天
- 员工、项目、任务、调用次数、聊天原文、消息数量、token 估算、耗时、错误状态
- 后端会继续把结构化 Trace 汇总到 AI 工作日页面

ChatGPT 桌面端说明

个人账号的 ChatGPT 桌面端不通过本地强抓、键盘记录、截图、cookie 抓取或 HTTPS 中间人方式监控。

如果必须覆盖桌面端，需要走 ChatGPT 企业工作区合规日志导入；否则请使用本安装包创建的 ChatGPT 网页版受监控入口。

安全说明

- 密码只用于登录，不写入安装包。
- 通用包本身不含员工专属令牌。
- CC Switch 遥测令牌由安装时登录后签发。
- ChatGPT 网页版插件只在 chatgpt.com / chat.openai.com 和智慧大脑检测页生效。
- 插件会采集 ChatGPT 网页对话原文，请在公司制度和员工知情范围内使用。

卸载

先退出 CC Switch，再运行：

   powershell -ExecutionPolicy Bypass -File .\Uninstall-AIMonitor.ps1

当前仍是局域网 HTTP 试运行环境。外地员工需要 VPN 或公网 HTTPS 网关，正式推广前建议升级 HTTPS。
