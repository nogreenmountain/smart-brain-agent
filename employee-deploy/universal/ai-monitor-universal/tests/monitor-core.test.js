const assert = require("assert");
const {
  normalizeMessages,
  estimateTokens,
  buildSessionMetrics,
  stableConversationId,
} = require("../chatgpt-web-extension/monitor-core.js");

const rawMessages = [
  { role: "user", content: "  请解释 AI 监控。  " },
  { role: "assistant", content: "可以分为三路接入。" },
  { role: "unknown", content: "drop me" },
  { role: "assistant", content: "" },
  { role: "tool", content: "工具输出" },
];

const messages = normalizeMessages(rawMessages);
assert.deepStrictEqual(
  messages.map((message) => message.role),
  ["user", "assistant", "tool"],
);
assert.strictEqual(messages[0].content, "请解释 AI 监控。");
assert.ok(estimateTokens("123456789") >= 3);

const metrics = buildSessionMetrics(messages);
assert.strictEqual(metrics.messageCount, 3);
assert.ok(metrics.promptTokens > 0);
assert.ok(metrics.completionTokens > 0);
assert.strictEqual(
  metrics.totalTokens,
  metrics.promptTokens + metrics.completionTokens,
);

assert.strictEqual(
  stableConversationId("https://chatgpt.com/c/abc-123", "fallback"),
  "chatgpt-web:c/abc-123",
);
assert.strictEqual(
  stableConversationId("https://chatgpt.com/", "fallback"),
  "chatgpt-web:fallback",
);

console.log("monitor-core tests passed");
