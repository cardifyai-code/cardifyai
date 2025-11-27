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
  logEvent("info", "contentScript loaded on CardifyLabs dashboard", {
    url: window.location.href,
  });
}

/**
 * Reserved hook: if in the future you want the site itself to react
 * to extension presence (e.g., show a “Connected via Extension” badge),
 * you can toggle DOM here.
 */
function markExtensionPresence() {
  try {
    const body = document.body;
    if (!body) return;

    // Add a data-attribute that your Jinja/JS can look for if needed.
    body.dataset.cardifyaiExtension = "true";
  } catch (e) {
    logEvent("warn", "Failed to mark extension presence", { error: String(e) });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  announceLoaded();
  markExtensionPresence();

  // NOTE:
  // We intentionally do NOT:
  //  - listen for CARDIFY_START
  //  - send CARDIFY_GENERATE
  // Those flows are now handled entirely inside background.js via
  // chrome.scripting + direct fetch() to /api/extension/generate.
});
