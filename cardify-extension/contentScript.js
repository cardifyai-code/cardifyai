// contentScript.js
// Injected only on https://cardifylabs.com/* (see manifest.json)
// Currently used for lightweight logging and future UI hooks on the Cardify site.

/**
 * Structured console logging helper.
 */
function logEvent(level, message, details = {}) {
  const payload = {
    source: "CardifyAI-extension-content",
    level,
    message,
    details,
    ts: new Date().toISOString(),
  };

  if (level === "error") {
    console.error("[CardifyAI/content]", payload);
  } else if (level === "warn") {
    console.warn("[CardifyAI/content]", payload);
  } else {
    console.log("[CardifyAI/content]", payload);
  }
}

/**
 * Optional: small banner in dev tools so you can see the script is active.
 */
function announceLoaded() {
  logEvent("info", "contentScript loaded on CardifyLabs page", {
    url: window.location.href,
  });
}

/**
 * Reserved hook: mark that the extension is present on the Cardify site.
 * Your Flask templates or client-side JS can look for:
 *   document.body.dataset.cardifyaiExtension === "true"
 * to show a “Connected via Extension” badge or tweak UI.
 */
function markExtensionPresence() {
  try {
    const body = document.body;
    if (!body) {
      logEvent("warn", "document.body not ready when marking extension presence");
      return;
    }

    body.dataset.cardifyaiExtension = "true";
    logEvent("info", "Marked extension presence on body dataset");
  } catch (e) {
    logEvent("warn", "Failed to mark extension presence", { error: String(e) });
  }
}

/**
 * (Optional) Future hook:
 * If you ever want the site to react to specific messages from the background
 * script, you can handle them here.
 *
 * For now we keep this NO-OP so it doesn't interfere with the background.js
 * flow, which injects directly and does not depend on this content script.
 */
// chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
//   logEvent("info", "Received message in contentScript", { message });
//   // No-op for now
// });

document.addEventListener("DOMContentLoaded", () => {
  announceLoaded();
  markExtensionPresence();

  // NOTE:
  // We intentionally do NOT:
  //  - listen for CARDIFY_START
  //  - send CARDIFY_GENERATE
  // or auto-fill the dashboard form.
  //
  // Those flows are handled entirely in background.js via:
  //   - chrome.scripting.executeScript()
  //   - direct interaction with /dashboard DOM
});
