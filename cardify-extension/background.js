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
 * Injects code into the Cardify dashboard page that:
 * - Pastes selected text into the <textarea id="input_text">
 * - Sets #card_count
 * - Clicks the "Generate Cards" button
 */
async function injectAutoFill(tabId, text, numCards) {
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (selectedText, count) => {
      function waitForElement(selector, timeout = 8000) {
        return new Promise((resolve, reject) => {
          const start = Date.now();
          const timer = setInterval(() => {
            const el = document.querySelector(selector);
            if (el) {
              clearInterval(timer);
              resolve(el);
            }
            if (Date.now() - start > timeout) {
              clearInterval(timer);
              reject("Element not found: " + selector);
            }
          }, 200);
        });
      }

      (async () => {
        try {
          // Show loading message
          alert("CardifyAI: Preparing your flashcards...");

          const textarea = await waitForElement("#input_text");
          const countBox = await waitForElement("#card_count");
          const generateBtn = await waitForElement("#generate_btn");

          textarea.value = selectedText;
          countBox.value = count;

          generateBtn.click();

        } catch (err) {
          alert("CardifyAI: Auto-fill error → " + err);
        }
      })();
    },
    args: [text, numCards]
  });
}

/**
 * Call backend to generate cards.
 */
async function handleGenerateRequest(payload) {
  try {
    const { text, num_cards } = payload;

    if (!text || !text.trim()) {
      return { ok: false, reason: "no_text" };
    }

    const apiUrl = `${CARDIFY_BASE}/api/extension/generate`;

    const resp = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ text, num_cards })
    });

    if (resp.status === 401) {
      await openOrFocusTab("/auth/login?next=/dashboard");
      return { ok: false, reason: "not_logged_in" };
    }

    if (resp.status === 402 || resp.status === 403) {
      const data = await resp.json().catch(() => ({}));
      const redirectUrl = data.redirect_url || "/billing/portal";
      await openOrFocusTab(redirectUrl);
      return { ok: false, reason: "billing_required" };
    }

    if (!resp.ok) {
      console.error("Backend error:", resp.status);
      return { ok: false, reason: "server_error", status: resp.status };
    }

    const data = await resp.json().catch(() => ({}));
    const redirectUrl =
      data.redirect_url ||
      data.deck_url ||
      "/dashboard";

    const tab = await openOrFocusTab(redirectUrl);
    return { ok: true, tabId: tab.id };

  } catch (err) {
    console.error("Network error:", err);
    return { ok: false, reason: "network_error" };
  }
}

/**
 * MAIN USER ACTION:
 * When user clicks the extension icon:
 *  1. Get selected text
 *  2. Ask user for # of cards (via in-page prompt)
 *  3. Call backend
 *  4. Auto-fill dashboard and click "generate"
 */
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id) return;

  let selectedText = "";

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.getSelection().toString()
    });

    selectedText = (result || "").trim();
  } catch (err) {
    console.error("Selection error:", err);
  }

  if (!selectedText) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => alert("CardifyAI: Please highlight some text first.")
      });
    } catch {}
    return;
  }

  // Ask user how many cards they want
  let count = null;

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const defaultCount = "20";
        const v = prompt("How many flashcards (1–200)?", defaultCount);
        if (v === null) return null;
        let n = parseInt(v.trim(), 10);
        if (!Number.isFinite(n)) return null;
        return Math.max(1, Math.min(n, 200));
      }
    });

    count = result;
  } catch (err) {
    console.error("Prompt error:", err);
  }

  if (count === null) return;

  // Backend request
  const response = await handleGenerateRequest({
    text: selectedText,
    num_cards: count
  });

  if (!response.ok) return;

  // Auto-fill the dashboard
  if (response.tabId) {
    setTimeout(() => injectAutoFill(response.tabId, selectedText, count), 1200);
  }
});

/**
 * Context Menu: same logic but replaces selectionText → info.selectionText
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
  if (!selectedText) return;

  // Ask for number of cards
  let count = null;

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const v = prompt("How many flashcards (1–200)?", "20");
        if (v === null) return null;
        let n = parseInt(v.trim(), 10);
        return Math.max(1, Math.min(n, 200));
      }
    });
    count = result;
  } catch {}

  if (count === null) return;

  const response = await handleGenerateRequest({
    text: selectedText,
    num_cards: count
  });

  if (!response.ok) return;

  if (response.tabId) {
    setTimeout(() => injectAutoFill(response.tabId, selectedText, count), 1200);
  }
});
