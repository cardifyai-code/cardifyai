// background.js
// Service worker for "Cardify with CardifyAI"

const CARDIFY_BASE = "https://cardifylabs.com";

/**
 * Helper: open CardifyLabs URL, focusing an existing tab if one is already open.
 * This avoids spawning a bunch of duplicate tabs.
 *
 * Accepts either:
 *  - full URL (https://cardifylabs.com/...)
 *  - path (/dashboard, billing/portal, etc.)
 */
async function openOrFocus(pathOrUrl) {
  const url = pathOrUrl.startsWith("http")
    ? pathOrUrl
    : `${CARDIFY_BASE}${pathOrUrl.startsWith("/") ? pathOrUrl : "/" + pathOrUrl}`;

  const tabs = await chrome.tabs.query({ url: CARDIFY_BASE + "/*" });

  if (tabs.length > 0) {
    // Focus first matching tab, and optionally update its URL if different
    const target = tabs[0];
    await chrome.tabs.update(target.id, { active: true, url });
    await chrome.windows.update(target.windowId, { focused: true });
  } else {
    await chrome.tabs.create({ url });
  }
}

/**
 * Call CardifyAI backend to generate cards.
 * Backend is responsible for:
 *  - Checking login status
 *  - Checking subscription tier (Premium / Professional)
 *  - Returning appropriate HTTP status codes
 */
async function handleGenerateRequest(payload, sendResponse) {
  try {
    const { text, num_cards } = payload || {};

    if (!text || !text.trim()) {
      sendResponse({
        ok: false,
        reason: "no_text"
      });
      return;
    }

    const apiUrl = `${CARDIFY_BASE}/api/extension/generate`;

    const resp = await fetch(apiUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      // Important: include cookies so the Flask session / Google login is used
      credentials: "include",
      body: JSON.stringify({
        text,
        num_cards
      })
    });

    // 401: Not logged in
    if (resp.status === 401) {
      await openOrFocus("/auth/login?next=/dashboard");
      sendResponse({
        ok: false,
        reason: "not_logged_in"
      });
      return;
    }

    // 402/403: Not Premium/Professional or subscription inactive
    if (resp.status === 402 || resp.status === 403) {
      let data = {};
      try {
        data = await resp.json();
      } catch (e) {
        data = {};
      }

      // Let backend optionally send a specific billing URL
      const redirectUrl = data.redirect_url || "/billing/portal";

      await openOrFocus(redirectUrl);
      sendResponse({
        ok: false,
        reason: "billing_required"
      });
      return;
    }

    // Other non-OK error
    if (!resp.ok) {
      console.error("CardifyAI extension API error:", resp.status);
      sendResponse({
        ok: false,
        reason: "server_error",
        status: resp.status
      });
      return;
    }

    // Success: open the deck or dashboard
    const data = await resp.json().catch(() => ({}));

    const redirectUrl =
      data.redirect_url ||
      data.deck_url ||
      "/dashboard";

    await openOrFocus(redirectUrl);

    sendResponse({
      ok: true,
      reason: "success"
    });
  } catch (err) {
    console.error("CardifyAI extension fetch failed:", err);
    sendResponse({
      ok: false,
      reason: "network_error"
    });
  }
}

/**
 * When the user clicks the toolbar icon, tell the content script on the
 * active tab to start the "Cardify" flow (grab selection + ask how many cards).
 */
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id) return;

  try {
    await chrome.tabs.sendMessage(tab.id, { type: "CARDIFY_START" });
  } catch (err) {
    console.error("Error sending CARDIFY_START:", err);
  }
});

/**
 * Create context menu for right-click on selected text.
 */
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "cardify-generate-selection",
    title: "Generate flashcards with CardifyAI",
    contexts: ["selection"]
  });
});

/**
 * Handle context menu clicks.
 */
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "cardify-generate-selection" && tab && tab.id) {
    try {
      // Just trigger the same flow as clicking the icon
      await chrome.tabs.sendMessage(tab.id, { type: "CARDIFY_START" });
    } catch (err) {
      console.error("Error sending CARDIFY_START from context menu:", err);
    }
  }
});

/**
 * Listen for messages from content scripts.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) {
    return;
  }

  if (message.type === "CARDIFY_GENERATE") {
    // message.payload: { text, num_cards }
    handleGenerateRequest(message.payload, sendResponse);
    // Indicate we will respond asynchronously
    return true;
  }
});
