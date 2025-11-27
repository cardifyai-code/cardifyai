// contentScript.js
// Runs on all pages and talks to the background service worker.

// Used so we don't trigger multiple runs on the same page in quick succession.
let isRunningCardify = false;

/**
 * Structured console logging helper.
 */
function logEvent(level, message, details = {}) {
  const payload = {
    source: "CardifyAI-extension",
    level,
    message,
    details,
    ts: new Date().toISOString()
  };

  if (level === "error") {
    console.error("[CardifyAI]", payload);
  } else if (level === "warn") {
    console.warn("[CardifyAI]", payload);
  } else {
    console.log("[CardifyAI]", payload);
  }
}

/**
 * Simple full-screen loading overlay for progress + errors.
 */
function showOverlay(text, isError = false) {
  let overlay = document.getElementById("cardifyai-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "cardifyai-overlay";
    overlay.style.position = "fixed";
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.right = "0";
    overlay.style.bottom = "0";
    overlay.style.background = "rgba(0, 0, 0, 0.45)";
    overlay.style.zIndex = "999999";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";
    overlay.style.pointerEvents = "none";

    const box = document.createElement("div");
    box.id = "cardifyai-overlay-box";
    box.style.minWidth = "260px";
    box.style.maxWidth = "420px";
    box.style.background = "#111827";
    box.style.color = "#e5e7eb";
    box.style.borderRadius = "10px";
    box.style.padding = "14px 18px";
    box.style.fontFamily =
      'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    box.style.fontSize = "14px";
    box.style.boxShadow = "0 10px 25px rgba(0, 0, 0, 0.5)";
    box.style.border = "1px solid rgba(156, 163, 175, 0.6)";
    box.style.display = "flex";
    box.style.flexDirection = "column";
    box.style.gap = "6px";

    const title = document.createElement("div");
    title.id = "cardifyai-overlay-title";
    title.style.fontWeight = "600";
    title.textContent = "CardifyAI";

    const message = document.createElement("div");
    message.id = "cardifyai-overlay-message";
    message.style.fontSize = "13px";

    const sub = document.createElement("div");
    sub.id = "cardifyai-overlay-sub";
    sub.style.fontSize = "11px";
    sub.style.opacity = "0.75";

    box.appendChild(title);
    box.appendChild(message);
    box.appendChild(sub);
    overlay.appendChild(box);
    document.documentElement.appendChild(overlay);
  }

  const msgEl = overlay.querySelector("#cardifyai-overlay-message");
  const subEl = overlay.querySelector("#cardifyai-overlay-sub");

  if (msgEl) msgEl.textContent = text || "";
  if (subEl) {
    subEl.textContent = isError
      ? "Check your CardifyAI tab or try again."
      : "Please keep this tab open while we prepare your flashcards.";
  }

  overlay.style.display = "flex";

  // Color tweak for error state
  const box = overlay.querySelector("#cardifyai-overlay-box");
  if (box) {
    box.style.borderColor = isError
      ? "rgba(248, 113, 113, 0.8)"
      : "rgba(156, 163, 175, 0.6)";
  }
}

/**
 * Hide the loading overlay (if present).
 */
function hideOverlay() {
  const overlay = document.getElementById("cardifyai-overlay");
  if (overlay) {
    overlay.style.display = "none";
  }
}

/**
 * Safely get the user's selected text from either:
 * - normal page selection, or
 * - focused input/textarea selection
 */
function getSelectedText() {
  let selectedText = "";

  // Primary: window selection
  if (window.getSelection) {
    selectedText = window.getSelection().toString();
  }

  // Fallback: selection inside an input/textarea
  if ((!selectedText || !selectedText.trim()) && document.activeElement) {
    const el = document.activeElement;
    const tag = el.tagName && el.tagName.toLowerCase();

    if (
      tag === "textarea" ||
      (tag === "input" &&
        el.type &&
        ["text", "search", "url", "email", "tel"].includes(
          el.type.toLowerCase()
        ))
    ) {
      const start = el.selectionStart || 0;
      const end = el.selectionEnd || 0;
      selectedText = (el.value || "").substring(start, end);
    }
  }

  return (selectedText || "").trim();
}

/**
 * Starts the Cardify flow:
 * - Collects selected text
 * - Prompts user for number of flashcards
 * - Shows loading overlay
 * - Sends text + count to background.js to call the CardifyAI backend
 * - Reacts to success/error with logs + UI
 */
async function startCardifyFlow() {
  if (isRunningCardify) {
    logEvent("info", "startCardifyFlow ignored; already running");
    return;
  }
  isRunningCardify = true;

  logEvent("info", "startCardifyFlow invoked");

  try {
    const selectedText = getSelectedText();

    if (!selectedText) {
      logEvent("warn", "No text selected");
      alert("CardifyAI: Please highlight some text first.");
      return;
    }

    // Show initial overlay
    showOverlay("Preparing your selection…");
    logEvent("info", "Selection captured", {
      length: selectedText.length
    });

    // Load the last used number of cards from sync storage as a default
    let defaultCount = "20";
    try {
      const stored = await chrome.storage.sync.get("lastCardCount");
      const lastCardCount = stored?.lastCardCount;
      if (
        Number.isFinite(lastCardCount) &&
        lastCardCount > 0 &&
        lastCardCount <= 200
      ) {
        defaultCount = String(lastCardCount);
      }
    } catch (e) {
      logEvent("warn", "Unable to read lastCardCount from storage", {
        error: String(e)
      });
    }

    let countStr = prompt(
      "How many flashcards would you like to generate? (1–200)",
      defaultCount
    );

    if (countStr === null) {
      // User hit cancel
      logEvent("info", "User cancelled card count prompt");
      hideOverlay();
      return;
    }

    countStr = countStr.trim();
    if (!countStr) {
      alert("CardifyAI: Please enter a number between 1 and 200.");
      hideOverlay();
      return;
    }

    let num = parseInt(countStr, 10);
    if (!Number.isFinite(num)) {
      alert("CardifyAI: Please enter a valid number.");
      hideOverlay();
      return;
    }

    // Clamp between 1 and 200
    if (num < 1) num = 1;
    if (num > 200) num = 200;

    logEvent("info", "Using card count", { num });

    // Persist the last used value
    try {
      await chrome.storage.sync.set({ lastCardCount: num });
    } catch (e) {
      logEvent("warn", "Unable to save lastCardCount to storage", {
        error: String(e)
      });
    }

    // Update overlay for backend call
    showOverlay("Contacting CardifyAI and generating your flashcards…");

    // Send message to background to call backend
    chrome.runtime.sendMessage(
      {
        type: "CARDIFY_GENERATE",
        payload: {
          text: selectedText,
          num_cards: num
        }
      },
      (response) => {
        if (chrome.runtime.lastError) {
          logEvent("error", "runtime error when sending message", {
            error: chrome.runtime.lastError.message
          });
          showOverlay(
            "Extension error: unable to talk to CardifyAI. Try reloading the page and extension.",
            true
          );
          setTimeout(hideOverlay, 3500);
          return;
        }

        if (!response) {
          logEvent("error", "No response from background");
          showOverlay(
            "No response from CardifyAI extension. Try again in a moment.",
            true
          );
          setTimeout(hideOverlay, 3500);
          return;
        }

        logEvent("info", "Received response from background", { response });

        if (!response.ok) {
          if (response.reason === "not_logged_in") {
            showOverlay(
              "You need to log in to CardifyAI. A login tab has been opened.",
              true
            );
          } else if (response.reason === "billing_required") {
            showOverlay(
              "This feature is for Premium & Professional users. A billing page has been opened.",
              true
            );
          } else if (response.reason === "no_text") {
            showOverlay(
              "No text was provided to generate flashcards.",
              true
            );
          } else if (response.reason === "server_error") {
            showOverlay(
              "CardifyAI server error. Please try again in a moment.",
              true
            );
          } else if (response.reason === "network_error") {
            showOverlay(
              "Network error talking to CardifyAI. Check your connection and try again.",
              true
            );
          } else {
            showOverlay(
              "Something went wrong generating your flashcards.",
              true
            );
          }

          setTimeout(hideOverlay, 4000);
        } else {
          // Success: background.js already opened/focused the Cardify tab.
          showOverlay("Success! Opening your CardifyAI deck…");
          setTimeout(hideOverlay, 2500);
        }
      }
    );
  } catch (err) {
    logEvent("error", "Unexpected error in startCardifyFlow", {
      error: String(err),
      stack: err && err.stack
    });
    alert("CardifyAI: Unexpected error occurred. Please try again.");
    hideOverlay();
  } finally {
    isRunningCardify = false;
  }
}

/**
 * Listen for the signal from background.js when the user clicks the extension icon
 * or uses the context menu.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) return;

  if (message.type === "CARDIFY_START") {
    startCardifyFlow();
  }
});
