import json
from typing import List, Dict

from flask import current_app
from openai import OpenAI

from .config import SYSTEM_PROMPT

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
    Robustly extract text from the new OpenAI Responses API.

    We handle possibilities like:
      - item.type == "message"
      - item.content -> list of parts
        - part.type == "output_text" with part.output_text.text
        - part.type == "text" with part.text
      - if all else fails, we fall back to str(part)
    """
    text_chunks: List[str] = []

    output = getattr(response, "output", None) or getattr(response, "outputs", None)
    if not output:
        return ""

    for item in output:
        item_type = getattr(item, "type", None)
        if item_type and item_type != "message":
            continue

        # Most current SDKs: the content is directly on the item
        contents = getattr(item, "content", None)
        if contents is None:
            # Extremely defensive: some variants might use item.message.content
            message_obj = getattr(item, "message", None)
            if message_obj is not None:
                contents = getattr(message_obj, "content", None)

        if not contents:
            continue

        for part in contents:
            c_type = getattr(part, "type", None)

            # Try output_text.text first
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
    model = current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini")

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
        # No 'reasoning' parameter – compatible with gpt-4.1-mini, o3-mini, etc.
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

    # As an ultra-defensive fallback, if still empty, try stringifying the response
    if not raw_output:
        try:
            raw_output = str(response) or ""
        except Exception:
            raw_output = ""

    raw_output = raw_output.strip()
    if not raw_output:
        raise RuntimeError("Model returned empty output.")

    # Try to parse as JSON
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError:
        # Fallback: look for a JSON array inside the text
        start = raw_output.find("[")
        end = raw_output.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(raw_output[start : end + 1])
            except Exception:
                raise RuntimeError("Could not parse JSON from model output.")
        else:
            raise RuntimeError("Model output did not contain valid JSON.")

    if not isinstance(data, list):
        raise RuntimeError("Model output JSON is not a list of flashcards.")

    flashcards: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        front = str(item.get("front", "")).strip()
        back = str(item.get("back", "")).strip()
        if front and back:
            flashcards.append({"front": front, "back": back})

    if not flashcards:
        raise RuntimeError("No valid flashcards generated from model output.")

    # Trim if model returned more than requested
    if len(flashcards) > num_cards:
        flashcards = flashcards[:num_cards]

    return flashcards
