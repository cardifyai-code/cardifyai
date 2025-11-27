// background.js
// Service worker for "Cardify with CardifyAI"

const CARDIFY_BASE = "https://cardifylabs.com";

/**
 * Small helper to build a full URL from a path or url.
 */
function toAbsoluteUrl(pathOrUrl) {
  if (!pathOrUrl) {
    return `${CARDIFY_BASE}/dashboard`;
  }
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  if (!pathOrUrl.startsWith("/")) {
    return `${CARDIFY_BASE}/${pathOrUrl}`;
  }
  return `${CARDIFY_BASE}${pathOrUrl}`;
}

/**
 * Show a full-page loading overlay in the current tab.
 * This runs IN THE PAGE via chrome.scripting.
 */
async function showLoadingOverlay(tabId, message) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (msg) => {
        // If it already exists, just update text
        let overlay = document.getElementById("cardifyai-ext-overlay");
        if (!overlay) {
          overlay = document.createElement("div");
          overlay.id = "cardifyai-ext-overlay";
          overlay.style.position = "fixed";
          overlay.style.inset = "0";
          overlay.style.backgroundColor = "rgba(0,0,0,0.45)";
          overlay.style.zIndex = "2147483647";
          overlay.style.display = "flex";
          overlay.style.flexDirection = "column";
          overlay.style.alignItems = "center";
          overlay.style.justifyContent = "center";
          overlay.style.backdropFilter = "blur(2px)";
          overlay.style.color = "#fff";
          overlay.style.fontFamily =
            "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

          const box = document.createElement("div");
          box.style.backgroundColor = "rgba(0,0,0,0.8)";
          box.style.borderRadius = "12px";
          box.style.padding = "16px 24px";
          box.style.display = "flex";
          box.style.flexDirection = "column";
          box.style.alignItems = "center";
          box.style.gap = "10px";
          box.style.minWidth = "220px";
          box.id = "cardifyai-ext-overlay-box";

          const spinner = document.createElement("div");
          spinner.style.width = "32px";
          spinner.style.height = "32px";
          spinner.style.borderRadius = "50%";
          spinner.style.border = "4px solid rgba(255,255,255,0.3)";
          spinner.style.borderTopColor = "#ffffff";
          spinner.style.animation = "cardifyai-spin 0.9s linear infinite";

          const text = document.createElement("div");
          text.id = "cardifyai-ext-overlay-text";
          text.style.fontSize = "14px";
          text.style.textAlign = "center";

          text.textContent = msg || "Sending selection to CardifyAI...";

          box.appendChild(spinner);
          box.appendChild(text);
          overlay.appendChild(box);
          document.body.appendChild(overlay);

          // Inject spinner keyframes
          const style = document.createElement("style");
          style.textContent = `
            @keyframes cardifyai-spin {
              0% { transform: rotate(0deg); }
              100% { transform: rotate(360deg); }
            }
          `;
          document.head.appendChild(style);
        } else {
          const text = document.getElementById("cardifyai-ext-overlay-text");
          if (text) {
            text.textContent = msg || "Sending selection to CardifyAI...";
          }
        }
      },
      args: [message || "Sending selection to CardifyAI..."]
    });
  } catch (err) {
    console.warn("[CardifyAI] Could not show loading overlay:", err);
  }
}

/**
 * Remove the loading overlay if present.
 */
async function hideLoadingOverlay(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const overlay = document.getElementById("cardifyai-ext-overlay");
        if (overlay && overlay.parentNode) {
          overlay.parentNode.removeChild(overlay);
        }
      }
    });
  } catch (err) {
    // It’s fine if this fails (e.g., tab navigated away)
    console.warn("[CardifyAI] Could not hide loading overlay:", err);
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
 * Call backend /api/extension/generate with POST.
 * This keeps the text in the BODY, so large inputs are safe.
 */
async function callExtensionAPI(tabId, text, numCards) {
  await showLoadingOverlay(
    tabId,
    "CardifyAI: Sending your selection to generate flashcards..."
  );

  try {
    const apiUrl = `${CARDIFY_BASE}/api/extension/generate`;

    const resp = await fetch(apiUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      credentials: "include", // send cookies for session / login
      body: JSON.stringify({
        text,
        num_cards: numCards
      })
    });

    // Not logged in
    if (resp.status === 401) {
      await hideLoadingOverlay(tabId);
      await chrome.tabs.update(tabId, {
        url: `${CARDIFY_BASE}/auth/login?next=/dashboard`,
        active: true
      });
      try {
        await chrome.scripting.executeScript({
          target: { tabId },
          func: () => alert("CardifyAI: Please log in to continue.")
        });
      } catch (_) {}
      return;
    }

    // Not premium/professional or billing issue
    if (resp.status === 402 || resp.status === 403) {
      const data = await resp.json().catch(() => ({}));
      const redirectUrl = toAbsoluteUrl(
        data.redirect_url || "/billing/portal"
      );

      await hideLoadingOverlay(tabId);
      await chrome.tabs.update(tabId, { url: redirectUrl, active: true });

      try {
        await chrome.scripting.executeScript({
          target: { tabId },
          func: () =>
            alert(
              "CardifyAI: This feature is for paid plans. Opening billing to update your subscription."
            )
        });
      } catch (_) {}
      return;
    }

    if (!resp.ok) {
      console.error("[CardifyAI] Server error:", resp.status);
      await hideLoadingOverlay(tabId);
      try {
        await chrome.scripting.executeScript({
          target: { tabId },
          func: () =>
            alert(
              "CardifyAI: Server error while generating flashcards. Please try again."
            )
        });
      } catch (_) {}
      return;
    }

    const data = await resp.json().catch(() => ({}));
    const redirectUrl = toAbsoluteUrl(
      data.redirect_url || data.deck_url || "/dashboard"
    );

    await hideLoadingOverlay(tabId);
    await chrome.tabs.update(tabId, { url: redirectUrl, active: true });
  } catch (err) {
    console.error("[CardifyAI] Network error:", err);
    await hideLoadingOverlay(tabId);
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: () =>
          alert(
            "CardifyAI: Network error while contacting the server. Please check your connection and try again."
          )
      });
    } catch (_) {}
  }
}

/**
 * Main flow used by:
 *  - Toolbar icon click
 *  - Context menu
 *
 * Steps:
 *  1) Collect text + num_cards from the page
 *  2) POST to /api/extension/generate (body, NOT URL)
 *  3) Backend does login/plan/quota checks + generation
 *  4) Backend responds with redirect_url → we navigate the current tab there
 */
async function startCardifyFlow(tab, selectionOverride) {
  if (!tab || !tab.id) return;

  if (!tab.url || !tab.url.startsWith("http")) {
    console.warn("[CardifyAI] Ignoring non-http tab:", tab.url);
    return;
  }

  const collected = await collectFromPage(tab.id, selectionOverride || "");
  if (!collected) {
    return; // user cancelled or error
  }

  await callExtensionAPI(tab.id, collected.text, collected.num_cards);
}

/**
 * Toolbar icon click
 */
chrome.action.onClicked.addListener(async (tab) => {
  startCardifyFlow(tab, null);
});

/**
 * Context Menu: use info.selectionText as hint
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
