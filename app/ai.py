import json
from typing import List, Dict

from flask import current_app
from openai import OpenAI

from .config import SYSTEM_PROMPT

# Global client cache
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """
    Lazily construct a global OpenAI client using the API key from config.
    """
    global _client
    if _client is None:
        api_key = current_app.config.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        _client = OpenAI(api_key=api_key)
    return _client


def _extract_text_from_response(response) -> str:
    """
    Robustly extract text from the OpenAI Responses API output.

    Handles shapes like:
      response.output or response.outputs
      each item.type == "message"
      item.content -> list of parts
        - part.output_text.text
        - part.text
    Falls back to str(part) if needed.
    """
    text_chunks: List[str] = []

    output = getattr(response, "output", None) or getattr(response, "outputs", None)
    if not output:
        return ""

    for item in output:
        item_type = getattr(item, "type", None)
        if item_type and item_type != "message":
            continue

        contents = getattr(item, "content", None)
        if contents is None:
            # Some SDKs have item.message.content instead
            message_obj = getattr(item, "message", None)
            if message_obj is not None:
                contents = getattr(message_obj, "content", None)

        if not contents:
            continue

        for part in contents:
            # Try part.output_text.text first
            if hasattr(part, "output_text"):
                ot = getattr(part, "output_text", None)
                txt = getattr(ot, "text", None) if ot is not None else None
                if txt:
                    text_chunks.append(txt)
                    continue

            # Then try plain .text
            txt = getattr(part, "text", None)
            if txt:
                text_chunks.append(txt)
                continue

            # Fallback: string representation
            try:
                fallback_txt = str(part)
                if fallback_txt:
                    text_chunks.append(fallback_txt)
            except Exception:
                continue

    return "".join(text_chunks).strip()


def generate_flashcards_from_text(
    text: str,
    num_cards: int = 10,
    style: str = "high-yield",
) -> List[Dict[str, str]]:
    """
    Use OpenAI to generate flashcards as a list of {front, back} dicts.

    Behavior:
    - Read the full text (including any PDF-extracted text).
    - Analyze the text sentence by sentence.
    - Identify topics and important concepts.
    - Generate up to `num_cards` high-quality flashcards covering those topics.
    """

    if not text or not text.strip():
        raise RuntimeError("No source text provided for flashcard generation.")

    client = _get_client()
    # Default from config is "gpt-4o-mini", but allow override
    model = current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")

    # Build the user prompt that instructs the model how to behave
    prompt = (
        "You will be given study content.\n\n"
        "Your task:\n"
        "- Go sentence by sentence through the content.\n"
        "- Identify the topics and key concepts in those sentences.\n"
        "- Group related sentences into topics.\n"
        f"- Generate up to {num_cards} flashcards that test those topics.\n\n"
        "Flashcard requirements:\n"
        "- Each card must be a JSON object with 'front' and 'back'.\n"
        "- 'front' is a question or prompt that references a specific concept or topic.\n"
        "- 'back' is the correct, concise answer.\n"
        "- You may use definitions, mechanisms, cause–effect, comparisons, or fill-in-the-blank.\n"
        "- Avoid duplicates and trivial rephrasings.\n"
        "- Focus on the most important, exam-relevant topics.\n\n"
        f"Style requested by the user: {style}\n\n"
        "Return JSON ONLY in this exact format:\n"
        '[{\"front\": \"...\", \"back\": \"...\"}, ...]\n\n'
        "Source content:\n"
        f"{text}"
    )

    try:
        # Responses API call (no reasoning param so it's compatible with gpt-4o-mini)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}") from e

    # Extract text robustly
    try:
        raw_output = _extract_text_from_response(response)
    except Exception as e:
        raise RuntimeError(f"Unexpected format from OpenAI response: {e}") from e

    # Ultra-defensive: if still empty, fall back to stringifying the response
    if not raw_output:
        try:
            raw_output = str(response) or ""
        except Exception:
            raw_output = ""

    raw_output = raw_output.strip()
    if not raw_output:
        raise RuntimeError("Model returned empty output.")

    # Try to parse JSON
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError:
        # Attempt to recover if model wrapped JSON in extra text
        try:
            start = raw_output.index("[")
            end = raw_output.rindex("]") + 1
            data = json.loads(raw_output[start:end])
        except Exception as e:
            raise RuntimeError(
                "Model did not return valid JSON flashcard list."
            ) from e

    if not isinstance(data, list):
        raise RuntimeError("Model response JSON is not a list.")

    cards: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        front = (item.get("front") or "").strip()
        back = (item.get("back") or "").strip()
        if not front or not back:
            continue
        cards.append({"front": front, "back": back})

        if len(cards) >= num_cards:
            break

    if not cards:
        raise RuntimeError("No valid flashcards were parsed from the model output.")

    return cards
