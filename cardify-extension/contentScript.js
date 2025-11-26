// contentScript.js
// Runs on all pages and talks to the background service worker.

// Used so we don't trigger multiple runs on the same page in quick succession.
let isRunningCardify = false;

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
 * - Sends text + count to background.js to call the CardifyAI backend
 */
async function startCardifyFlow() {
  if (isRunningCardify) {
    return;
  }
  isRunningCardify = true;

  try {
    const selectedText = getSelectedText();

    if (!selectedText) {
      alert("CardifyAI: Please highlight some text first.");
      return;
    }

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
      console.warn("CardifyAI: unable to read lastCardCount from storage", e);
    }

    let countStr = prompt(
      "How many flashcards would you like to generate? (1–200)",
      defaultCount
    );

    if (countStr === null) {
      // User hit cancel
      return;
    }

    countStr = countStr.trim();
    if (!countStr) {
      alert("CardifyAI: Please enter a number between 1 and 200.");
      return;
    }

    let num = parseInt(countStr, 10);
    if (!Number.isFinite(num)) {
      alert("CardifyAI: Please enter a valid number.");
      return;
    }

    // Clamp between 1 and 200
    if (num < 1) num = 1;
    if (num > 200) num = 200;

    // Persist the last used value
    try {
      await chrome.storage.sync.set({ lastCardCount: num });
    } catch (e) {
      console.warn("CardifyAI: unable to save lastCardCount to storage", e);
    }

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
          console.warn(
            "CardifyAI: runtime error when sending message:",
            chrome.runtime.lastError.message
          );
          return;
        }

        if (!response) {
          console.warn("CardifyAI: No response from background.");
          return;
        }

        if (!response.ok) {
          if (response.reason === "not_logged_in") {
            alert(
              "CardifyAI: You need to log in first. A CardifyAI tab has been opened for you."
            );
          } else if (response.reason === "billing_required") {
            alert(
              "CardifyAI: This feature is for Premium & Professional users. A billing page has been opened for you."
            );
          } else if (response.reason === "no_text") {
            alert("CardifyAI: No text was provided to generate flashcards.");
          } else {
            alert(
              "CardifyAI: Something went wrong. Please try again in a moment."
            );
          }
        } else {
          // Success: background.js already opened/focused the Cardify tab.
          console.log("CardifyAI: flashcard generation requested successfully.");
        }
      }
    );
  } catch (err) {
    console.error("CardifyAI content script error:", err);
    alert("CardifyAI: Unexpected error occurred. Please try again.");
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
