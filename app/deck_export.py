import io
import csv
import json
import random
import time
from typing import List, Dict

import genanki


def _normalize_flashcards(
    flashcards: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """
    Normalize flashcard dicts to always have lowercase 'front' and 'back' keys
    and ensure they are strings.
    """
    normalized: List[Dict[str, str]] = []

    for card in flashcards or []:
        if not isinstance(card, dict):
            continue

        front = (
            card.get("front")
            or card.get("Front")
            or card.get("question")
            or card.get("Question")
        )
        back = (
            card.get("back")
            or card.get("Back")
            or card.get("answer")
            or card.get("Answer")
        )

        if not front or not back:
            continue

        normalized.append(
            {
                "front": str(front),
                "back": str(back),
            }
        )

    return normalized


def create_apkg_from_flashcards(
    flashcards: List[Dict[str, str]],
    deck_name: str = "CardifyLabs Deck",
) -> io.BytesIO:
    """
    Create an Anki .apkg file from flashcards using genanki.
    Returns an in-memory BytesIO suitable for Flask send_file().
    """
    cards = _normalize_flashcards(flashcards)

    deck_id = int(time.time()) + random.randint(0, 1_000_000)
    model_id = deck_id + 1

    my_model = genanki.Model(
        model_id,
        "CardifyLabs Basic Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{Front}}<br><br>{{Back}}",
            },
        ],
    )

    my_deck = genanki.Deck(deck_id, deck_name)

    for card in cards:
        note = genanki.Note(
            model=my_model,
            fields=[card["front"], card["back"]],
        )
        my_deck.add_note(note)

    package = genanki.Package(my_deck)
    mem_stream = io.BytesIO()
    package.write_to_file(mem_stream)
    mem_stream.seek(0)
    return mem_stream


def create_csv_from_flashcards(
    flashcards: List[Dict[str, str]],
) -> io.BytesIO:
    """
    Create a CSV export of flashcards.
    Returns an in-memory BytesIO suitable for Flask send_file().
    """
    cards = _normalize_flashcards(flashcards)

    text_stream = io.StringIO()
    writer = csv.writer(text_stream)
    writer.writerow(["Front", "Back"])

    for card in cards:
        writer.writerow([card["front"], card["back"]])

    # Convert text to bytes
    bytes_stream = io.BytesIO(text_stream.getvalue().encode("utf-8"))
    bytes_stream.seek(0)
    return bytes_stream


def create_json_from_flashcards(
    flashcards: List[Dict[str, str]],
    deck_name: str = "CardifyLabs Deck",
) -> io.BytesIO:
    """
    Optional JSON export of flashcards (not strictly needed, but handy).
    Returns an in-memory BytesIO.
    """
    cards = _normalize_flashcards(flashcards)

    payload = {
        "deck_name": deck_name,
        "cards": cards,
    }

    bytes_stream = io.BytesIO(json.dumps(payload, indent=2).encode("utf-8"))
    bytes_stream.seek(0)
    return bytes_stream


# --------------------------------------------------------------------
# Backwards-compatible aliases (in case any old code still imports
# create_apkg_from_cards / create_csv_from_cards).
# --------------------------------------------------------------------


def create_apkg_from_cards(
    cards: List[Dict[str, str]],
    deck_name: str = "CardifyLabs Deck",
) -> io.BytesIO:
    return create_apkg_from_flashcards(cards, deck_name=deck_name)


def create_csv_from_cards(
    cards: List[Dict[str, str]],
) -> io.BytesIO:
    return create_csv_from_flashcards(cards)
