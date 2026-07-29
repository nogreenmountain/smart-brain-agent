(function runSmartBrainBridge() {
  "use strict";

  const CONFIG = globalThis.AI_MONITOR_CONFIG || {};
  const manifest = chrome.runtime.getManifest();

  function componentReports() {
    const version = manifest && manifest.version ? manifest.version : null;
    return [
      {
        name: "chatgpt_web_extension",
        status: "installed",
        version,
        details: { source: "smartbrain_setup_bridge" }
      },
      {
        name: "browser_shortcut",
        status: "installed",
        version: CONFIG.packageVersion || version,
        details: { source: "extension_loaded_browser_window" }
      }
    ];
  }

  async function postStatus() {
    const at = new Date().toISOString();
    window.postMessage(
      {
        type: "AI_MONITOR_SETUP_STATUS",
        installed: true,
        version: manifest && manifest.version ? manifest.version : undefined,
        deviceId: CONFIG.deviceId || undefined,
        source: "chatgpt_web_extension",
        at
      },
      window.location.origin
    );
    try {
      await chrome.runtime.sendMessage({
        type: "AI_MONITOR_REGISTER_COMPONENT",
        components: componentReports()
      });
    } catch (_) {
      // The setup page still receives the local install signal; server registration
      // will succeed after the employee logs in to SmartBrain in this browser.
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (event.data && event.data.type === "AI_MONITOR_SETUP_STATUS_REQUEST") {
      postStatus();
    }
  });

  postStatus();
})();
