# app/ai.py

import json
import re
from typing import List, Dict, Tuple

from openai import OpenAI

from .config import Config, SYSTEM_PROMPT

client = OpenAI()


def _clean_text(text: str) -> str:
    """
    Basic preprocessing:
    - Normalize newlines
    - Collapse repeated whitespace
    - Strip leading/trailing spaces
    - Remove obvious junk control characters
    """
    if not text:
        return ""

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove non-printable control chars except common whitespace
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t ")

    # Collapse multiple blank lines
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

    # Collapse long runs of spaces/tabs
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def _segment_text(text: str, max_chars: int = 6000) -> List[str]:
    """
    Split text into reasonably sized segments (by characters) while trying to
    cut at paragraph or sentence boundaries.

    We segment so that:
      - We can send each segment to OpenAI within limits.
      - We still 'use' all of the text by processing every segment.
    """
    text = _clean_text(text)
    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    segments: List[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + max_chars, n)
        # Try to cut at a newline or sentence boundary near 'end'
        cut = end

        # Look backwards a bit for a good break
        window_start = max(start, end - 800)
        window = text[window_start:end]

        # Prefer paragraph breaks
        newline_idx = window.rfind("\n\n")
        if newline_idx != -1:
            cut = window_start + newline_idx
        else:
            # Try sentence boundary
            period_idx = window.rfind(". ")
            if period_idx != -1:
                cut = window_start + period_idx + 1  # include period

        if cut <= start:
            # Fallback: hard cut at 'end'
            cut = end

        segment = text[start:cut].strip()
        if segment:
            segments.append(segment)

        start = cut

    return segments


def _normalize_cards(raw: str) -> List[Dict[str, str]]:
    """
    Parse the model response as JSON and normalize into:
      [{"front": "...", "back": "..."}, ...]
    """
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to salvage JSON inside text if there's extra logging
        try:
            start = raw.index("[")
            end = raw.rindex("]") + 1
            data = json.loads(raw[start:end])
        except Exception:
            return []

    if not isinstance(data, list):
        return []

    cards: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        front = (
            item.get("front")
            or item.get("Front")
            or item.get("question")
            or item.get("Question")
        )
        back = (
            item.get("back")
            or item.get("Back")
            or item.get("answer")
            or item.get("Answer")
        )
        if not front or not back:
            continue
        cards.append({"front": str(front).strip(), "back": str(back).strip()})

    return cards


def _extract_usage_tokens(response) -> Tuple[int, int]:
    """
    Safely extract input/output token counts from the OpenAI response.

    Returns:
      (input_tokens, output_tokens)
    """
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0

    # Newer style: input_tokens / output_tokens
    in_tokens = getattr(usage, "input_tokens", None)
    out_tokens = getattr(usage, "output_tokens", None)

    # Fallback to older style: prompt_tokens / completion_tokens
    if in_tokens is None and hasattr(usage, "prompt_tokens"):
        in_tokens = usage.prompt_tokens
    if out_tokens is None and hasattr(usage, "completion_tokens"):
        out_tokens = usage.completion_tokens

    try:
        in_tokens = int(in_tokens or 0)
    except Exception:
        in_tokens = 0

    try:
        out_tokens = int(out_tokens or 0)
    except Exception:
        out_tokens = 0

    return in_tokens, out_tokens


def _call_openai_for_segment(
    segment_text: str,
    segment_index: int,
    total_segments: int,
    target_cards: int,
) -> Tuple[List[Dict[str, str]], int, int]:
    """
    Call OpenAI for a single segment of the text.

    We pass:
      - SYSTEM_PROMPT (global "how to behave")
      - user message describing:
          * This is segment i of N
          * Use all important info from this segment
          * Produce up to 'target_cards' cards
      - Extra constraints to force concrete, passage-anchored answers.

    Returns:
      (cards, input_tokens, output_tokens)
    """
    if target_cards <= 0:
        return [], 0, 0

    # Safety clamp
    target_cards = max(1, min(target_cards, 2000))

    user_instructions = f"""
You are processing segment {segment_index + 1} of {total_segments} from a larger document.

Your job is to:
1. Identify every important, testable concept in THIS SEGMENT ONLY.
2. Turn those concepts into high-quality flashcards.
3. Use as much of the information in this segment as possible,
   focusing on distinct, non-trivial facts.

STRICT ANSWER RULES:
- Every answer must be explicitly and unambiguously supported by the segment text.
- Do NOT create questions whose answers require outside knowledge, personal opinion,
  or multiple equally correct answers.
- Avoid vague or conceptual questions like "Why is X important?" unless the passage
  explicitly gives a very specific answer.
- Prefer concrete facts, definitions, lists, cause-effect relationships, numerical values,
  and clearly stated comparisons or distinctions from the text.

Return up to {target_cards} flashcards for **this segment** as JSON,
following the system instructions.
Here is the segment text:

\"\"\"{segment_text}\"\"\"
    """.strip()

    response = client.chat.completions.create(
        model=Config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_instructions},
        ],
        temperature=0.3,
    )

    content = response.choices[0].message.content or ""
    cards = _normalize_cards(content)
    in_tokens, out_tokens = _extract_usage_tokens(response)
    return cards, in_tokens, out_tokens


def generate_flashcards_from_text(
    source_text: str,
    num_cards: int = 10,
) -> Tuple[List[Dict[str, str]], int, int]:
    """
    Main API for the rest of the app.

    - Preprocesses & segments the input text.
    - Calls OpenAI once per segment, telling it:
        * "Use all the important info in this segment."
        * "Return up to X cards for this segment."
      (this combines the 'identify concepts' and 'final card writing'
       into a single call per segment).
    - Enforces that answers are overtly derivable from the passage (see instructions).
    - Merges and deduplicates cards across segments.
    - Trims to at most num_cards cards.

    Returns:
      (cards, total_input_tokens, total_output_tokens)
    """
    cleaned = _clean_text(source_text)
    if not cleaned:
        return [], 0, 0

    # Safety on num_cards
    if num_cards <= 0:
        num_cards = 1
    if num_cards > 2000:
        num_cards = 2000

    segments = _segment_text(cleaned)
    if not segments:
        return [], 0, 0

    total_length = sum(len(s) for s in segments)
    remaining_cards = num_cards

    all_cards: List[Dict[str, str]] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for idx, segment in enumerate(segments):
        if remaining_cards <= 0:
            break

        # Allocate cards roughly proportional to segment length
        if total_length > 0:
            proportion = len(segment) / total_length
        else:
            proportion = 1 / len(segments)

        # At least 1 card, but not more than remaining
        segment_target = max(1, int(round(proportion * num_cards)))
        if segment_target > remaining_cards:
            segment_target = remaining_cards

        seg_cards, seg_in, seg_out = _call_openai_for_segment(
            segment_text=segment,
            segment_index=idx,
            total_segments=len(segments),
            target_cards=segment_target,
        )

        all_cards.extend(seg_cards)
        remaining_cards -= len(seg_cards)

        total_input_tokens += seg_in
        total_output_tokens += seg_out

    # Deduplicate by (front, back)
    seen = set()
    deduped: List[Dict[str, str]] = []
    for card in all_cards:
        key = (card["front"], card["back"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)

    # If model returned more than requested across segments, trim.
    if len(deduped) > num_cards:
        deduped = deduped[:num_cards]

    return deduped, total_input_tokens, total_output_tokens
