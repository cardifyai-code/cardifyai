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
 * Small helper: show a loading overlay on the current page.
 * It will be removed when we redirect or if we explicitly call removeLoadingOverlay.
 */
async function showLoadingOverlay(tabId, message) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (msg) => {
        let overlay = document.getElementById("cardifyai-extension-overlay");
        if (!overlay) {
          overlay = document.createElement("div");
          overlay.id = "cardifyai-extension-overlay";
          overlay.style.position = "fixed";
          overlay.style.top = "16px";
          overlay.style.right = "16px";
          overlay.style.zIndex = "999999";
          overlay.style.padding = "12px 16px";
          overlay.style.background = "rgba(0,0,0,0.85)";
          overlay.style.color = "#fff";
          overlay.style.borderRadius = "8px";
          overlay.style.fontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
          overlay.style.fontSize = "13px";
          overlay.style.display = "flex";
          overlay.style.alignItems = "center";
          overlay.style.gap = "8px";

          // simple spinner
          const spinner = document.createElement("div");
          spinner.className = "cardifyai-spinner";
          spinner.style.width = "16px";
          spinner.style.height = "16px";
          spinner.style.border = "2px solid rgba(255,255,255,0.4)";
          spinner.style.borderTopColor = "#fff";
          spinner.style.borderRadius = "50%";
          spinner.style.animation = "cardifyai-spin 0.9s linear infinite";

          const text = document.createElement("span");
          text.id = "cardifyai-extension-overlay-text";

          overlay.appendChild(spinner);
          overlay.appendChild(text);
          document.body.appendChild(overlay);

          // keyframes
          const styleEl = document.createElement("style");
          styleEl.textContent = `
            @keyframes cardifyai-spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
          `;
          document.head.appendChild(styleEl);
        }

        const textNode = document.getElementById("cardifyai-extension-overlay-text");
        if (textNode) {
          textNode.textContent = msg || "CardifyAI: Working…";
        }
      },
      args: [message || "CardifyAI: Sending selection to Cardify…"]
    });
  } catch (err) {
    console.warn("[CardifyAI] Could not show loading overlay:", err);
  }
}

/**
 * Update the overlay text (e.g., on error or success).
 */
async function updateLoadingOverlay(tabId, message) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (msg) => {
        const textNode = document.getElementById("cardifyai-extension-overlay-text");
        if (textNode) {
          textNode.textContent = msg;
        }
      },
      args: [message]
    });
  } catch (err) {
    console.warn("[CardifyAI] Could not update loading overlay:", err);
  }
}

/**
 * Remove the overlay (if it exists).
 */
async function removeLoadingOverlay(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const overlay = document.getElementById("cardifyai-extension-overlay");
        if (overlay && overlay.parentNode) {
          overlay.parentNode.removeChild(overlay);
        }
      }
    });
  } catch (err) {
    console.warn("[CardifyAI] Could not remove loading overlay:", err);
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
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: () => alert("CardifyAI: Please highlight some text first.")
      });
    } catch (err) {
      console.warn("[CardifyAI] Unable to show alert:", err);
    }
    return null;
  }

  // 2) Prompt user for number of cards
  let numCards = null;

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const v = prompt("How many flashcards would you like to generate? (1–200)", "20");
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
 * Actually call the backend API:
 * POST https://cardifylabs.com/api/extension/generate
 * Body: { text, num_cards }
 *
 * The API:
 *  - checks login
 *  - checks subscription
 *  - generates cards & stores them in DB + session["cards"]
 *  - returns JSON with a redirect_url (usually /dashboard)
 */
async function handleGenerateRequestFromPage(tabId, payload) {
  await showLoadingOverlay(tabId, "CardifyAI: Generating flashcards…");

  try {
    const { text, num_cards } = payload;

    const resp = await fetch(`${CARDIFY_BASE}/api/extension/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      credentials: "include", // IMPORTANT so Flask session / login is used
      body: JSON.stringify({ text, num_cards })
    });

    let data = {};
    try {
      data = await resp.json();
    } catch {
      data = {};
    }

    // Not logged in
    if (resp.status === 401 || data.reason === "not_logged_in") {
      await updateLoadingOverlay(tabId, "CardifyAI: Please log in first…");
      await openOrFocusTab("/auth/login?next=/dashboard");
      // overlay will disappear once user leaves the page; we also remove explicitly:
      await removeLoadingOverlay(tabId);
      return;
    }

    // Billing / subscription issue
    if (resp.status === 402 || resp.status === 403 || data.reason === "billing_required") {
      await updateLoadingOverlay(tabId, "CardifyAI: Subscription required. Opening billing…");
      const billingUrl = data.redirect_url || "/billing/portal";
      await openOrFocusTab(billingUrl);
      await removeLoadingOverlay(tabId);
      return;
    }

    if (!resp.ok || data.ok === false) {
      console.error("[CardifyAI] Server error:", resp.status, data);
      await updateLoadingOverlay(tabId, "CardifyAI: Error generating cards. Try again.");
      setTimeout(() => removeLoadingOverlay(tabId), 2500);
      return;
    }

    // Success → open dashboard (or whatever redirect_url is)
    const redirectUrl = data.redirect_url || "/dashboard";

    await updateLoadingOverlay(tabId, "CardifyAI: Done! Opening Cardify…");
    await openOrFocusTab(redirectUrl);
    // Remove overlay on the original page
    await removeLoadingOverlay(tabId);
  } catch (err) {
    console.error("[CardifyAI] Network error:", err);
    await updateLoadingOverlay(tabId, "CardifyAI: Network error. Try again.");
    setTimeout(() => removeLoadingOverlay(tabId), 2500);
  }
}

/**
 * Core flow used by:
 *  - Toolbar icon click
 *  - Context menu
 *
 * Steps:
 *  1) Collect text + num_cards from the page
 *  2) POST to /api/extension/generate (JSON body → supports large text)
 *  3) Backend generates cards & stores in session
 *  4) We open/focus /dashboard so user sees the ready-made cards
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
    // user cancelled / no selection
    return;
  }

  await handleGenerateRequestFromPage(tab.id, collected);
}

/**
 * MAIN USER ACTION:
 * When user clicks the extension icon:
 *  1. Get selected text (from page)
 *  2. Ask user for # of cards (via in-page prompt)
 *  3. POST to /api/extension/generate
 *  4. Redirect to /dashboard where cards are already ready
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
