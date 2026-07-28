(function attachMonitorCore(root) {
  "use strict";

  const VALID_ROLES = new Set(["user", "assistant", "system", "tool"]);

  function estimateTokens(text) {
    const value = String(text || "").trim();
    if (!value) return 0;
    const asciiCount = Array.from(value).filter((char) => char.charCodeAt(0) < 128).length;
    const nonAsciiCount = Array.from(value).length - asciiCount;
    return Math.max(1, Math.ceil(asciiCount / 4 + nonAsciiCount * 0.8));
  }

  function normalizeMessages(rawMessages) {
    const seen = new Set();
    const normalized = [];
    for (const item of rawMessages || []) {
      const role = String(item && item.role ? item.role : "").toLowerCase();
      const content = String(item && item.content ? item.content : "").trim();
      if (!VALID_ROLES.has(role) || !content) continue;
      const key = `${role}\n${content}`;
      if (seen.has(key)) continue;
      seen.add(key);
      normalized.push({
        role,
        content,
        message_id: item.message_id || null,
        token_count: Number.isFinite(item.token_count) ? item.token_count : estimateTokens(content),
        metadata: item.metadata && typeof item.metadata === "object" ? item.metadata : {},
      });
    }
    return normalized;
  }

  function buildSessionMetrics(messages) {
    let promptTokens = 0;
    let completionTokens = 0;
    for (const message of messages || []) {
      const count = Number.isFinite(message.token_count)
        ? message.token_count
        : estimateTokens(message.content);
      if (message.role === "assistant" || message.role === "tool") {
        completionTokens += count;
      } else {
        promptTokens += count;
      }
    }
    return {
      messageCount: (messages || []).length,
      promptTokens,
      completionTokens,
      totalTokens: promptTokens + completionTokens,
    };
  }

  function stableConversationId(href, fallback) {
    let suffix = String(fallback || "untitled").trim() || "untitled";
    try {
      const url = new URL(href || "");
      const path = url.pathname.replace(/^\/+|\/+$/g, "");
      if (path) suffix = path;
    } catch (_) {
      // Keep fallback.
    }
    return `chatgpt-web:${suffix}`;
  }

  const api = {
    estimateTokens,
    normalizeMessages,
    buildSessionMetrics,
    stableConversationId,
  };

  root.AIMonitorCore = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
