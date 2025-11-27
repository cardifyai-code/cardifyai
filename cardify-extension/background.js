// background.js
// Service worker for "Cardify with CardifyAI"

const CARDIFY_BASE = "https://cardifylabs.com";

/**
 * Focus Cardify /dashboard tab if one exists, otherwise open a new one.
 * Returns the tab object.
 */
async function openOrFocusTab(pathOrUrl = "/dashboard") {
  const url = pathOrUrl.startsWith("http")
    ? pathOrUrl
    : `${CARDIFY_BASE}${pathOrUrl.startsWith("/") ? pathOrUrl : "/" + pathOrUrl}`;

  // Prefer an existing Cardify tab
  const existingTabs = await chrome.tabs.query({ url: CARDIFY_BASE + "/*" });

  if (existingTabs.length > 0) {
    const tab = existingTabs[0];
    await chrome.tabs.update(tab.id, { active: true, url });
    await chrome.windows.update(tab.windowId, { focused: true });
    console.log("[CardifyAI/bg] Reusing Cardify tab", tab.id, url);
    return tab;
  }

  const newTab = await chrome.tabs.create({ url });
  console.log("[CardifyAI/bg] Created new Cardify tab", newTab.id, url);
  return newTab;
}

/**
 * Small helper: show a loading overlay on the current page.
 * It will be removed when we explicitly call removeLoadingOverlay.
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
          overlay.style.fontFamily =
            "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
          overlay.style.fontSize = "13px";
          overlay.style.display = "flex";
          overlay.style.alignItems = "center";
          overlay.style.gap = "8px";

          // Simple spinner
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

          // Keyframes
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
    console.warn("[CardifyAI/bg] Could not show loading overlay:", err);
  }
}

/**
 * Update the overlay text (e.g., on progress).
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
    console.warn("[CardifyAI/bg] Could not update loading overlay:", err);
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
    console.warn("[CardifyAI/bg] Could not remove loading overlay:", err);
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
        func: () => {
          console.log("[CardifyAI/injected] Collecting selection…");
          // Get selection from window
          let s = window.getSelection ? window.getSelection().toString() : "";

          // Fallback to active input/textarea
          if ((!s || !s.trim()) && document.activeElement) {
            const el = document.activeElement;
            const tag = el.tagName && el.tagName.toLowerCase();
            const type = (el.type || "").toLowerCase();

            if (
              tag === "textarea" ||
              (tag === "input" &&
                ["text", "search", "url", "email", "tel"].includes(type))
            ) {
              const start = el.selectionStart || 0;
              const end = el.selectionEnd || 0;
              s = (el.value || "").substring(start, end);
            }
          }

          s = (s || "").trim();
          console.log(
            "[CardifyAI/injected] Selection length:",
            s ? s.length : 0
          );
          return s;
        }
      });

      selectedText = (result || "").trim();
    } catch (err) {
      console.error("[CardifyAI/bg] Error getting selection:", err);
    }
  }

  if (!selectedText) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: () => alert("CardifyAI: Please highlight some text first.")
      });
    } catch (err) {
      console.warn("[CardifyAI/bg] Unable to show alert:", err);
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
    console.error("[CardifyAI/bg] Error in prompt:", err);
  }

  if (numCards === null) {
    // user cancelled or invalid
    return null;
  }

  console.log(
    "[CardifyAI/bg] Collected text length + num_cards:",
    selectedText.length,
    numCards
  );
  return { text: selectedText, num_cards: numCards };
}

/**
 * Inject code into the Cardify dashboard tab that:
 *  - waits for the form elements
 *  - fills them with our text + num_cards
 *  - submits the form
 */
async function fillDashboardForm(dashboardTabId, payload) {
  const { text, num_cards } = payload;

  console.log("[CardifyAI/bg] Injecting fillDashboardForm into tab", dashboardTabId);

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: dashboardTabId },
      func: (selectedText, count) => {
        console.log("[CardifyAI/injected] fillDashboardForm started", {
          selectedLength: selectedText ? selectedText.length : 0,
          count
        });

        function waitForElement(selector, timeout = 10000) {
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
                reject(new Error("Element not found: " + selector));
              }
            }, 150);
          });
        }

        (async () => {
          try {
            // Try by ID first, then by name as a fallback
            const textarea =
              document.getElementById("input_text") ||
              document.querySelector('textarea[name="text_content"]');
            const countInput =
              document.getElementById("card_count") ||
              document.querySelector('input[name="num_cards"]');
            const form =
              document.getElementById("generatorForm") ||
              document.querySelector("form#generatorForm") ||
              document.querySelector('form[action*="/dashboard"]');

            console.log("[CardifyAI/injected] Found elements:", {
              hasTextarea: !!textarea,
              hasCountInput: !!countInput,
              hasForm: !!form
            });

            // If any aren't present yet, wait for them explicitly
            const finalTextarea =
              textarea || (await waitForElement("#input_text"));
            const finalCountInput =
              countInput || (await waitForElement("#card_count"));
            const finalForm =
              form || (await waitForElement("#generatorForm"));

            console.log("[CardifyAI/injected] Final elements ready:", {
              hasTextarea: !!finalTextarea,
              hasCountInput: !!finalCountInput,
              hasForm: !!finalForm
            });

            finalTextarea.value = selectedText;
            finalCountInput.value = String(count);

            // Trigger input events so any listeners see the changes
            finalTextarea.dispatchEvent(new Event("input", { bubbles: true }));
            finalCountInput.dispatchEvent(new Event("input", { bubbles: true }));

            // Hook into the dashboard's own loading UI if present
            const loadingDiv = document.getElementById("loadingContainer");
            const mainDiv = document.getElementById("mainFormContainer");
            if (loadingDiv && mainDiv) {
              loadingDiv.classList.remove("d-none");
              mainDiv.classList.add("d-none");
            }

            console.log("[CardifyAI/injected] Submitting form now…");
            finalForm.submit();

            return { ok: true };
          } catch (e) {
            console.error("[CardifyAI/injected] Error auto-filling dashboard:", e);
            alert(
              "CardifyAI: Unable to auto-fill the dashboard. " +
                "Please paste your text manually.\n\n" +
                String(e)
            );
            return { ok: false, error: String(e) };
          }
        })();

        // Nothing meaningful to return synchronously; the async IIFE handles it
        return { started: true };
      },
      args: [text, num_cards]
    });

    console.log("[CardifyAI/bg] fillDashboardForm executeScript result:", results);
  } catch (err) {
    console.error("[CardifyAI/bg] Error injecting fillDashboardForm:", err);
  }
}

/**
 * Core flow used by:
 *  - Toolbar icon click
 *  - Context menu
 *
 * Steps:
 *  1) Collect text + num_cards from the page
 *  2) Show a small loading overlay on the source page
 *  3) Open/focus /dashboard
 *  4) When /dashboard finishes loading, inject JS that fills the form
 *     and submits it (no contentScript message needed).
 */
async function startCardifyFlow(tab, selectionOverride) {
  if (!tab || !tab.id) return;

  // Ignore non-http(s) tabs like chrome://, edge://, about:blank, etc.
  if (!tab.url || !tab.url.startsWith("http")) {
    console.warn("[CardifyAI/bg] Ignoring non-http tab:", tab.url);
    return;
  }

  const collected = await collectFromPage(tab.id, selectionOverride || "");
  if (!collected) {
    // user cancelled / no selection
    return;
  }

  // Show loading overlay on the page where the user invoked Cardify
  await showLoadingOverlay(tab.id, "CardifyAI: Opening Cardify dashboard…");

  // Open or focus the dashboard
  const dashboardTab = await openOrFocusTab("/dashboard");
  const sourceTabId = tab.id;

  console.log("[CardifyAI/bg] Dashboard tab status:", dashboardTab.status);

  // If the dashboard is already fully loaded, inject immediately
  if (dashboardTab.status === "complete") {
    await updateLoadingOverlay(
      sourceTabId,
      "CardifyAI: Filling your Cardify deck…"
    );
    await fillDashboardForm(dashboardTab.id, collected);
    await removeLoadingOverlay(sourceTabId);
    return;
  }

  // Otherwise, wait for the dashboard tab to finish loading
  const onUpdated = async (updatedTabId, info, updatedTab) => {
    if (updatedTabId !== dashboardTab.id || info.status !== "complete") return;
    if (!updatedTab.url || !updatedTab.url.startsWith(`${CARDIFY_BASE}/dashboard`)) return;

    chrome.tabs.onUpdated.removeListener(onUpdated);

    console.log("[CardifyAI/bg] Dashboard finished loading; injecting filler…");
    await updateLoadingOverlay(
      sourceTabId,
      "CardifyAI: Filling your Cardify deck…"
    );
    await fillDashboardForm(updatedTabId, collected);
    await removeLoadingOverlay(sourceTabId);
  };

  chrome.tabs.onUpdated.addListener(onUpdated);
}

/**
 * MAIN USER ACTION:
 * When user clicks the extension icon:
 *  1. Get selected text (from page)
 *  2. Ask user for # of cards (via in-page prompt)
 *  3. Open /dashboard
 *  4. Auto-fill and submit the form there
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
