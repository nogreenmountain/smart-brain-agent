importScripts("config.js", "monitor-core.js");

const CONFIG = globalThis.AI_MONITOR_CONFIG || {};

function apiUrl(path) {
  return `${String(CONFIG.apiBase || "").replace(/\/+$/, "")}${path}`;
}

async function parseResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_) {
    return { raw: text };
  }
}

async function postJson(path, payload) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    credentials: "include",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload || {})
  });
  const body = await parseResponse(response);
  if (!response.ok) {
    throw new Error((body && (body.detail || body.message)) || `HTTP ${response.status}`);
  }
  return body;
}

async function getJson(path) {
  const response = await fetch(apiUrl(path), {
    method: "GET",
    credentials: "include",
    headers: { "Accept": "application/json" }
  });
  const body = await parseResponse(response);
  if (!response.ok) {
    throw new Error((body && (body.detail || body.message)) || `HTTP ${response.status}`);
  }
  return body;
}

function normalizeLoginName(username) {
  const value = String(username || "").trim().toLowerCase();
  if (!value) throw new Error("请输入智慧大脑用户名");
  if (value.includes("@")) return value;
  return `${value}@${CONFIG.defaultEmailDomain || "local.dev"}`;
}

async function getDeviceId() {
  if (CONFIG.deviceId) return String(CONFIG.deviceId);
  const state = await chrome.storage.local.get(["aiMonitorDeviceId"]);
  if (state.aiMonitorDeviceId) return String(state.aiMonitorDeviceId);
  const id = `browser-${crypto.randomUUID()}`;
  await chrome.storage.local.set({ aiMonitorDeviceId: id });
  return id;
}

async function registerComponents(components) {
  const componentList = Array.isArray(components) ? components : [components];
  const deviceId = await getDeviceId();
  return postJson("/v4/ai-monitor/devices/register", {
    project_id: CONFIG.projectId,
    device_id: deviceId,
    device_name: CONFIG.employeeName || "Browser AI Monitor",
    installer_version: CONFIG.packageVersion || null,
    os: navigator.userAgent,
    components: componentList.filter(Boolean)
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (!message || !message.type) return { ok: false, error: "unknown message" };
    if (message.type === "AI_MONITOR_CONFIG") {
      return { ok: true, config: CONFIG };
    }
    if (message.type === "AI_MONITOR_LOGIN") {
      await postJson("/auth/login", {
        email: normalizeLoginName(message.username),
        password: String(message.password || "")
      });
      const me = await getJson("/v4/auth/me");
      await chrome.storage.local.set({
        aiMonitorLoggedIn: true,
        aiMonitorUser: me,
        aiMonitorProjectId: CONFIG.projectId
      });
      return { ok: true, me };
    }
    if (message.type === "AI_MONITOR_STATUS") {
      const state = await chrome.storage.local.get([
        "aiMonitorLoggedIn",
        "aiMonitorUser",
        "aiMonitorProjectId",
        "aiMonitorTaskId",
        "aiMonitorTaskTitle"
      ]);
      return { ok: true, state };
    }
    if (message.type === "AI_MONITOR_SAVE_TASK") {
      await chrome.storage.local.set({
        aiMonitorTaskId: String(message.taskId || "").trim(),
        aiMonitorTaskTitle: String(message.taskTitle || "").trim()
      });
      return { ok: true };
    }
    if (message.type === "AI_MONITOR_INGEST") {
      const result = await postJson("/v4/ai-chat/ingest", message.payload);
      return { ok: true, result };
    }
    if (message.type === "AI_MONITOR_REGISTER_COMPONENT") {
      const result = await registerComponents(message.components || message.component);
      return { ok: true, result };
    }
    return { ok: false, error: "unsupported message" };
  })()
    .then((response) => sendResponse(response))
    .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
  return true;
});
