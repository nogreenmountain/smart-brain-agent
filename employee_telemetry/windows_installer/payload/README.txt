智慧大脑 AI Monitor 一键安装器
版本：2026-08-10-r17-ccswitch-token-semantics-fix

适用范围

同一个 EXE 发给所有研发员工使用，不区分 test1、test2 或个人专属包。

它包含三类入口：

1. CC Switch / Claude Code / Codex 遥测配置
2. ChatGPT 网页版监控插件和受监控浏览器快捷方式
3. 智慧大脑网页安装检测入口

网页入口

智慧大脑：
https://39.105.79.0

安装检测页：
https://39.105.79.0/monitor/setup

员工安装步骤

1. 打开智慧大脑并进入“AI Monitor”页面。
2. 点击“下载一键安装器”，得到 SmartBrain-AIMonitor-Setup-latest.exe。
3. 从系统托盘彻底退出 CC Switch，并关闭正在运行的 Edge / Chrome。
4. 双击 EXE；若 Windows SmartScreen 提示未知发布者，核对文件来源后选择“更多信息 -> 仍要运行”。
5. 输入自己的智慧大脑用户名和密码，点击“立即安装”。短用户名会自动补全 @local.dev。
6. 安装完成后重新打开 CC Switch，分别切换一次 Claude 和 Codex 当前供应商。
7. 关闭并重新打开 Claude Code / Codex。
8. 使用桌面上的“ChatGPT Monitored - Edge”或“ChatGPT Monitored - Chrome”打开 ChatGPT 网页版。
9. 第一次打开独立浏览器配置时，重新登录个人 ChatGPT 账号。
10. 回到智慧大脑“AI Monitor”页面点击“重新检测”。

员工电脑不需要预装 Python，也不需要打开 CMD 或 PowerShell。密码只通过安装器标准输入传给登录程序，不出现在命令行、日志和安装文件中。

如果打开 ChatGPT Monitored 后没有右下角面板

请重新下载最新 EXE 并直接覆盖安装。安装器会重新创建受监控浏览器配置和快捷方式。

能监控什么

- CC Switch 转接的 Claude Code / Codex 调用
- ChatGPT 网页版个人账号聊天
- Codex、Claude 和 ChatGPT 网页中员工可见的完整用户消息与 AI 文本回复
- 每次对话使用的模型、输入 Token、输出 Token、总 Token、耗时和错误状态
- 后端会继续把结构化 Trace 汇总到 AI 工作日页面

Codex / Claude 对话同步

- 安装后立即同步最近 7 天的会话，此后每两分钟自动同步一次。
- 对话以每次用户提问和对应 AI 回复为一条记录，重复同步不会重复入库。
- 系统提示词、密钥、工具参数、命令输出和本地文件内容不会作为对话正文上传。

ChatGPT 桌面端说明

个人账号的 ChatGPT 桌面端不通过本地强抓、键盘记录、截图、cookie 抓取或 HTTPS 中间人方式监控。

如果必须覆盖桌面端，需要走 ChatGPT 企业工作区合规日志导入；否则请使用本安装包创建的 ChatGPT 网页版受监控入口。

安全说明

- 密码只用于登录，不写入安装包。
- 通用包本身不含员工专属令牌。
- CC Switch 遥测令牌由安装时登录后签发。
- 签名设备令牌保存在当前 Windows 用户的 AppData 运行目录，用于后台对话同步；不保存登录密码。
- ChatGPT 网页版插件只在 chatgpt.com / chat.openai.com 和智慧大脑检测页生效。
- 安装包会采集 Codex、Claude 和 ChatGPT 网页对话原文，请在公司制度和员工知情范围内使用。

卸载

先退出 CC Switch，再打开 Windows“设置 -> 应用 -> 已安装的应用”，找到“SmartBrain AI Monitor”并点击卸载。也可以再次运行已安装目录中的 SmartBrainAIMonitorSetup.exe --uninstall。

当前使用公网 IP + 私有 CA HTTPS。安装器会把内嵌根证书安装到当前 Windows 用户的受信任根证书库。
