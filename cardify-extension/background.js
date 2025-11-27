// background.js
// Service worker for "Cardify with CardifyAI"

const CARDIFY_BASE = "https://cardifylabs.com";

/**
 * Focus Cardify tab if one exists, otherwise open a new one.
 * Returns the tab object.
 */
async function openOrFocusTab(pathOrUrl = "/dashboard") {
  const url = pathOrUrl.startsWith("http")
    ? pathOrUrl
    : `${CARDIFY_BASE}${pathOrUrl.startsWith("/") ? pathOrUrl : "/" + pathOrUrl}`;

  const existingTabs = await chrome.tabs.query({ url: CARDIFY_BASE + "/*" });

  if (existingTabs.length > 0) {
    const tab = existingTabs[0];
    await chrome.tabs.update(tab.id, { active: true, url });
    await chrome.windows.update(tab.windowId, { focused: true });
    return tab;
  }

  return await chrome.tabs.create({ url });
}

/**
 * Utility: show an alert + console log inside the given tab.
 */
async function showAlertInPage(tabId, message) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (msg) => {
        try {
          console.log("[CardifyAI]", msg);
          alert(msg);
        } catch (e) {
          console.error("[CardifyAI] Failed to show alert:", e);
        }
      },
      args: [message]
    });
  } catch (err) {
    console.warn("[CardifyAI] Unable to inject alert into page:", err);
  }
}

/**
 * Collect selected text + number of cards from the active page.
 * Returns: { text, num_cards } or null if user cancelled / invalid.
 *
 * selectionOverride:
 *   - if provided (from context menu selection), we use that instead of
 *     calling window.getSelection() again.
 */
async function collectFromPage(tabId, selectionOverride) {
  // 1) Get selected text
  let selectedText = selectionOverride || "";

  if (!selectedText) {
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => window.getSelection().toString()
      });

      selectedText = (result || "").trim();
    } catch (err) {
      console.error("[CardifyAI] Error getting selection:", err);
    }
  }

  if (!selectedText) {
    await showAlertInPage(
      tabId,
      "CardifyAI: Please highlight some text first."
    );
    return null;
  }

  // 2) Prompt user for number of cards
  let numCards = null;

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const v = prompt(
          "How many flashcards would you like to generate? (1–200)",
          "20"
        );
        if (v === null) return null; // user cancelled
        const trimmed = v.trim();
        if (!trimmed) return null;
        let n = parseInt(trimmed, 10);
        if (!Number.isFinite(n)) return null;
        if (n < 1) n = 1;
        if (n > 200) n = 200;
        return n;
      }
    });

    numCards = result;
  } catch (err) {
    console.error("[CardifyAI] Error in prompt:", err);
  }

  if (numCards === null) {
    // user cancelled or invalid
    return null;
  }

  return { text: selectedText, num_cards: numCards };
}

/**
 * Call backend to generate cards via POST JSON.
 * Returns an object describing the result:
 *  - { ok: true, redirectUrl, tabId }
 *  - { ok: false, reason, status? }
 */
async function handleGenerateRequest(payload) {
  try {
    const { text, num_cards } = payload || {};

    if (!text || !text.trim()) {
      return { ok: false, reason: "no_text" };
    }

    console.log("[CardifyAI] Sending request to backend...", {
      length: text.length,
      num_cards
    });

    const apiUrl = `${CARDIFY_BASE}/api/extension/generate`;

    const resp = await fetch(apiUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      credentials: "include", // send cookies for Flask session / Google login
      body: JSON.stringify({ text, num_cards })
    });

    // 401: Not logged in
    if (resp.status === 401) {
      console.warn("[CardifyAI] Not logged in (401). Redirecting to login.");
      await openOrFocusTab("/auth/login?next=/dashboard");
      return { ok: false, reason: "not_logged_in", status: 401 };
    }

    // 402/403: Billing / subscription issue
    if (resp.status === 402 || resp.status === 403) {
      let data = {};
      try {
        data = await resp.json();
      } catch (e) {
        data = {};
      }
      const redirectUrl = data.redirect_url || "/billing/portal";
      console.warn(
        "[CardifyAI] Billing required (",
        resp.status,
        "). Redirect:",
        redirectUrl
      );
      await openOrFocusTab(redirectUrl);
      return { ok: false, reason: "billing_required", status: resp.status };
    }

    if (!resp.ok) {
      console.error(
        "[CardifyAI] Backend error:",
        resp.status,
        resp.statusText
      );
      return { ok: false, reason: "server_error", status: resp.status };
    }

    const data = await resp.json().catch(() => ({}));
    const redirectUrl =
      data.redirect_url ||
      data.deck_url ||
      "/dashboard";

    console.log("[CardifyAI] Backend success. Redirecting to:", redirectUrl);

    const tab = await openOrFocusTab(redirectUrl);
    return { ok: true, redirectUrl, tabId: tab.id };

  } catch (err) {
    console.error("[CardifyAI] Network error:", err);
    return { ok: false, reason: "network_error" };
  }
}

/**
 * Core flow used by:
 *  - Toolbar icon click
 *  - Context menu
 *
 * Steps:
 *  1) Collect text + num_cards from the page
 *  2) Call /api/extension/generate via POST (JSON body)
 *  3) Open /dashboard (or any redirect_url returned by backend)
 */
async function startCardifyFlow(tab, selectionOverride) {
  if (!tab || !tab.id) return;

  // Ignore non-http(s) tabs like chrome://, edge://, about:blank, etc.
  if (!tab.url || !tab.url.startsWith("http")) {
    console.warn("[CardifyAI] Ignoring non-http tab:", tab.url);
    return;
  }

  const collected = await collectFromPage(tab.id, selectionOverride || "");
  if (!collected) {
    // user cancelled or something failed already
    return;
  }

  // Inform the user we're sending the request
  await showAlertInPage(
    tab.id,
    "CardifyAI: Sending your highlighted text to generate flashcards. You'll be redirected to the dashboard."
  );

  const result = await handleGenerateRequest(collected);

  if (!result.ok) {
    // User-facing errors
    if (result.reason === "not_logged_in") {
      await showAlertInPage(
        tab.id,
        "CardifyAI: Please log in to your CardifyAI account. A login tab has been opened."
      );
    } else if (result.reason === "billing_required") {
      await showAlertInPage(
        tab.id,
        "CardifyAI: This feature is for paid plans. A billing page has been opened so you can update or start a subscription."
      );
    } else if (result.reason === "server_error") {
      await showAlertInPage(
        tab.id,
        "CardifyAI: Server error while generating flashcards. Please try again in a minute."
      );
    } else if (result.reason === "network_error") {
      await showAlertInPage(
        tab.id,
        "CardifyAI: Network error talking to CardifyAI. Check your connection and try again."
      );
    } else if (result.reason === "no_text") {
      // already handled earlier, but just in case
      await showAlertInPage(
        tab.id,
        "CardifyAI: No text found. Please highlight some text first."
      );
    } else {
      await showAlertInPage(
        tab.id,
        "CardifyAI: Something went wrong generating flashcards."
      );
    }
    return;
  }

  // Success: dashboard/deck tab is opened by handleGenerateRequest
  // Optional: small confirmation on the original page
  try {
    await showAlertInPage(
      tab.id,
      "CardifyAI: Request sent successfully. Your dashboard has been opened with the new flashcards."
    );
  } catch (e) {
    console.warn("[CardifyAI] Unable to show final success alert:", e);
  }
}

/**
 * MAIN USER ACTION:
 * When user clicks the extension icon:
 *  1. Get selected text (from page)
 *  2. Ask user for # of cards (via in-page prompt)
 *  3. POST to /api/extension/generate
 *  4. Open Cardify dashboard on success
 */
chrome.action.onClicked.addListener(async (tab) => {
  startCardifyFlow(tab, null);
});

/**
 * Context Menu: same logic but uses info.selectionText as a hint
 * for the selected text (more reliable on some pages).
 */
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "cardify-generate-selection",
    title: "Generate flashcards with CardifyAI",
    contexts: ["selection"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "cardify-generate-selection" || !tab?.id) return;

  const selectedText = (info.selectionText || "").trim();
  await startCardifyFlow(tab, selectedText || "");
});
