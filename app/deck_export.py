# app/deck_export.py

import io
import csv
import json
import random
import time
from typing import List, Dict, Any


def _normalize_cards(cards: List[Any]) -> List[Dict[str, str]]:
    """
    Normalize all cards into:
        [{"front": "...", "back": "..."}]

    Supports:
    - dict cards: {"front": "...", "back": "..."}
    - dict cards with capital keys or question/answer keys
    - model instances with .front and .back attributes
    """
    normalized = []

    for c in cards or []:
        # If it's already a dict
        if isinstance(c, dict):
            front = (
                c.get("front")
                or c.get("Front")
                or c.get("question")
                or c.get("Question")
            )
            back = (
                c.get("back")
                or c.get("Back")
                or c.get("answer")
                or c.get("Answer")
            )
        else:
            # Probably a Flashcard SQLAlchemy model
            front = getattr(c, "front", None)
            back = getattr(c, "back", None)

        if not front or not back:
            continue

        normalized.append({"front": str(front), "back": str(back)})

    return normalized


# ============================================================
# ANKI EXPORT (.apkg)
# ============================================================

def create_apkg_from_cards(cards: List[Any], deck_name: str = "CardifyAI Deck") -> io.BytesIO:
    """
    Create Anki .apkg deck from cards.
    """
    try:
        import genanki
    except ImportError as e:
        raise RuntimeError(
            "genanki is required for APKG export. "
            "Add 'genanki' to requirements.txt."
        ) from e

    cards = _normalize_cards(cards)

    deck_id = int(time.time()) + random.randint(0, 1_000_000)
    model_id = deck_id + 1

    model = genanki.Model(
        model_id,
        "CardifyAI Basic Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{Front}}<hr id=\"answer\">{{Back}}",
            }
        ],
    )

    deck = genanki.Deck(deck_id, deck_name)

    for c in cards:
        note = genanki.Note(
            model=model,
            fields=[c["front"], c["back"]],
        )
        deck.add_note(note)

    pkg = genanki.Package(deck)
    buf = io.BytesIO()
    pkg.write_to_file(buf)
    buf.seek(0)
    return buf


# ============================================================
# CSV EXPORT
# ============================================================

def create_csv_from_cards(cards: List[Any]) -> io.BytesIO:
    cards = _normalize_cards(cards)

    s = io.StringIO()
    writer = csv.writer(s)
    writer.writerow(["front", "back"])
    for c in cards:
        writer.writerow([c["front"], c["back"]])

    b = io.BytesIO(s.getvalue().encode("utf-8"))
    b.seek(0)
    return b


# ============================================================
# JSON EXPORT
# ============================================================

def create_json_from_cards(cards: List[Any]) -> io.BytesIO:
    """
    Export as simple list:
    [
      {"front": "...", "back": "..."},
      ...
    ]
    """
    cards = _normalize_cards(cards)
    payload = json.dumps(cards, ensure_ascii=False, indent=2).encode("utf-8")

    b = io.BytesIO(payload)
    b.seek(0)
    return b


# ============================================================
# LEGACY COMPATIBILITY (safe to keep)
# ============================================================

def create_apkg_from_flashcards(cards, deck_name="CardifyAI Deck"):
    return create_apkg_from_cards(cards, deck_name=deck_name)

def create_csv_from_flashcards(cards):
    return create_csv_from_cards(cards)

def create_json_from_flashcards(cards, deck_name="CardifyAI Deck"):
    return create_json_from_cards(cards)
