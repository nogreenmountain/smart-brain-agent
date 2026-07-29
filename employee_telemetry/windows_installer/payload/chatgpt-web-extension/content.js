(function runAIMonitorContent() {
  "use strict";

  const CONFIG = globalThis.AI_MONITOR_CONFIG || {};
  const CORE = globalThis.AIMonitorCore;
  let currentState = {};
  let lastSentHash = "";
  let sessionStartedAt = new Date().toISOString();
  let syncTimer = null;

  function sendMessage(message) {
    return chrome.runtime.sendMessage(message);
  }

  function setStatus(text) {
    const node = document.getElementById("ai-monitor-status");
    if (node) node.textContent = text;
  }

  function createPanel() {
    if (document.getElementById("ai-monitor-panel")) return;
    const panel = document.createElement("div");
    panel.id = "ai-monitor-panel";
    panel.innerHTML = `
      <div class="ai-monitor-head">
        <span>智慧大脑 AI Monitor</span>
        <button type="button" class="secondary" id="ai-monitor-toggle">收起</button>
      </div>
      <div class="ai-monitor-body">
        <label for="ai-monitor-username">智慧大脑用户名</label>
        <input id="ai-monitor-username" autocomplete="username" placeholder="test1" />
        <label for="ai-monitor-password">密码</label>
        <input id="ai-monitor-password" type="password" autocomplete="current-password" placeholder="只用于登录一次" />
        <div class="ai-monitor-row">
          <button type="button" id="ai-monitor-login">登录</button>
          <button type="button" class="secondary" id="ai-monitor-sync">立即同步</button>
        </div>
        <label for="ai-monitor-task-id">任务 ID</label>
        <input id="ai-monitor-task-id" placeholder="例如 task-auth 或留空" />
        <label for="ai-monitor-task-title">任务标题</label>
        <input id="ai-monitor-task-title" placeholder="例如 登录模块联调" />
        <div class="ai-monitor-row">
          <button type="button" id="ai-monitor-save-task">保存任务</button>
        </div>
        <div id="ai-monitor-status">未登录智慧大脑。</div>
      </div>
    `;
    document.documentElement.appendChild(panel);

    document.getElementById("ai-monitor-toggle").addEventListener("click", () => {
      panel.classList.toggle("ai-monitor-collapsed");
      document.getElementById("ai-monitor-toggle").textContent = panel.classList.contains("ai-monitor-collapsed") ? "展开" : "收起";
    });
    document.getElementById("ai-monitor-login").addEventListener("click", login);
    document.getElementById("ai-monitor-sync").addEventListener("click", () => syncConversation({ force: true }));
    document.getElementById("ai-monitor-save-task").addEventListener("click", saveTask);
  }

  async function refreshStatus() {
    const response = await sendMessage({ type: "AI_MONITOR_STATUS" });
    if (!response || !response.ok) {
      setStatus("无法读取插件状态。");
      return;
    }
    currentState = response.state || {};
    const taskId = currentState.aiMonitorTaskId || "";
    const taskTitle = currentState.aiMonitorTaskTitle || "";
    const taskIdInput = document.getElementById("ai-monitor-task-id");
    const taskTitleInput = document.getElementById("ai-monitor-task-title");
    if (taskIdInput && !taskIdInput.value) taskIdInput.value = taskId;
    if (taskTitleInput && !taskTitleInput.value) taskTitleInput.value = taskTitle;
    if (currentState.aiMonitorLoggedIn) {
      const email = currentState.aiMonitorUser && currentState.aiMonitorUser.email ? currentState.aiMonitorUser.email : "已登录";
      setStatus(`已连接智慧大脑：${email}`);
    } else {
      setStatus("未登录智慧大脑，暂不同步聊天记录。");
    }
  }

  async function login() {
    const username = document.getElementById("ai-monitor-username").value;
    const passwordNode = document.getElementById("ai-monitor-password");
    const password = passwordNode.value;
    setStatus("正在登录智慧大脑...");
    const response = await sendMessage({
      type: "AI_MONITOR_LOGIN",
      username,
      password
    });
    passwordNode.value = "";
    if (!response || !response.ok) {
      setStatus(`登录失败：${response && response.error ? response.error : "未知错误"}`);
      return;
    }
    await refreshStatus();
    await syncConversation({ force: true });
  }

  async function saveTask() {
    const taskId = document.getElementById("ai-monitor-task-id").value;
    const taskTitle = document.getElementById("ai-monitor-task-title").value;
    const response = await sendMessage({
      type: "AI_MONITOR_SAVE_TASK",
      taskId,
      taskTitle
    });
    if (!response || !response.ok) {
      setStatus(`任务保存失败：${response && response.error ? response.error : "未知错误"}`);
      return;
    }
    await refreshStatus();
    await syncConversation({ force: true });
  }

  function extractMessagesFromPage() {
    const nodes = Array.from(document.querySelectorAll("[data-message-author-role]"));
    const raw = nodes.map((node, index) => ({
      role: node.getAttribute("data-message-author-role"),
      content: node.innerText || node.textContent || "",
      message_id: node.getAttribute("data-message-id") || `dom-${index}`,
      metadata: { selector: "data-message-author-role" }
    }));
    return CORE.normalizeMessages(raw);
  }

  function payloadHash(payload) {
    return JSON.stringify({
      conversation_id: payload.conversation_id,
      task_id: payload.task_id,
      messages: payload.messages.map((message) => [message.role, message.content])
    });
  }

  async function syncConversation({ force = false } = {}) {
    if (!currentState.aiMonitorLoggedIn) {
      await refreshStatus();
      if (!currentState.aiMonitorLoggedIn) return;
    }
    const messages = extractMessagesFromPage();
    if (!messages.length) return;
    const metrics = CORE.buildSessionMetrics(messages);
    const now = new Date();
    const taskId = String(currentState.aiMonitorTaskId || "").trim() || "unassigned";
    const taskTitle = String(currentState.aiMonitorTaskTitle || "").trim() || (taskId === "unassigned" ? "未标记任务" : "");
    const payload = {
      project_id: CONFIG.projectId,
      source: CONFIG.source || "chatgpt_web",
      conversation_id: CORE.stableConversationId(window.location.href, document.title),
      title: document.title.replace(/\s+-\s+ChatGPT\s*$/i, "").trim() || "ChatGPT 网页会话",
      task_id: taskId,
      task_title: taskTitle,
      model: null,
      status: "ok",
      started_at: sessionStartedAt,
      ended_at: now.toISOString(),
      duration_ms: Math.max(0, now.getTime() - new Date(sessionStartedAt).getTime()),
      prompt_tokens: metrics.promptTokens,
      completion_tokens: metrics.completionTokens,
      total_tokens: metrics.totalTokens,
      cost: 0,
      error_count: 0,
      messages
    };
    const hash = payloadHash(payload);
    if (!force && hash === lastSentHash) return;
    const response = await sendMessage({ type: "AI_MONITOR_INGEST", payload });
    if (!response || !response.ok) {
      setStatus(`同步失败：${response && response.error ? response.error : "未知错误"}`);
      return;
    }
    lastSentHash = hash;
    setStatus(`已同步 ${messages.length} 条消息，估算 ${metrics.totalTokens} tokens。`);
  }

  function scheduleSync() {
    if (syncTimer) clearTimeout(syncTimer);
    syncTimer = setTimeout(() => syncConversation({ force: false }), 1800);
  }

  async function main() {
    if (!CORE || !CONFIG.projectId || !CONFIG.apiBase) return;
    createPanel();
    await refreshStatus();
    const observer = new MutationObserver(scheduleSync);
    observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true
    });
    scheduleSync();
  }

  main().catch((error) => setStatus(`AI Monitor 初始化失败：${error.message || error}`));
})();
