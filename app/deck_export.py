import io
import csv
import genanki
from typing import List, Dict, Any


# Stable deterministic IDs (important for Anki)
MODEL_ID = 1607392319
DECK_ID = 2059400110


def _build_anki_model() -> genanki.Model:
    """
    Create a basic front/back card model for Anki.
    """
    return genanki.Model(
        MODEL_ID,
        "CardifyAI Basic Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{Front}}<br><hr id='answer'>{{Back}}",
            }
        ],
    )


def create_apkg_from_cards(cards: List[Dict[str, Any]], deck_name: str = "CardifyAI Deck") -> bytes:
    """
    Build an Anki .apkg file from cards:
      [{"front": "...", "back": "..."}, ...]
    Returns bytes for direct download.
    """
    model = _build_anki_model()
    deck = genanki.Deck(DECK_ID, deck_name)

    for index, card in enumerate(cards):
        front = (card.get("front") or "").strip()
        back = (card.get("back") or "").strip()

        if not front or not back:
            continue

        # Stable GUID from card contents
        guid = str(abs(hash(front + back + str(index))))

        note = genanki.Note(
            model=model,
            fields=[front, back],
            guid=guid,
        )

        deck.add_note(note)

    pkg = genanki.Package(deck)
    stream = io.BytesIO()
    pkg.write_to_buffer(stream)

    return stream.getvalue()


def create_csv_from_cards(cards: List[Dict[str, Any]]) -> bytes:
    """
    Export cards to CSV. Returns UTF-8 encoded CSV bytes.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Front", "Back"])  # Header row

    for card in cards:
        front = (card.get("front") or "").replace("\n", " ").strip()
        back = (card.get("back") or "").replace("\n", " ").strip()

        if not front or not back:
            continue

        writer.writerow([front, back])

    csv_data = output.getvalue()
    output.close()

    # Add BOM so Excel loads correctly
    return ("\ufeff" + csv_data).encode("utf-8")