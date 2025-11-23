import io
import csv
import json
import random
import time
from typing import List, Dict

import genanki


def create_apkg_from_flashcards(
    flashcards: List[Dict[str, str]],
    deck_name: str = "CardifyAI Deck",
) -> bytes:
    """Create an .apkg file from flashcards using genanki and return bytes."""
    deck_id = int(time.time()) + random.randint(0, 1000000)
    model_id = deck_id + 1

    my_model = genanki.Model(
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
                "afmt": "{{Front}}<br><br>{{Back}}",
            },
        ],
    )

    my_deck = genanki.Deck(deck_id, deck_name)

    for card in flashcards:
        note = genanki.Note(
            model=my_model,
            fields=[card["front"], card["back"]],
        )
        my_deck.add_note(note)

    package = genanki.Package(my_deck)
    mem_stream = io.BytesIO()
    package.write_to_file(mem_stream)
    mem_stream.seek(0)
    return mem_stream.read()


def create_csv_from_flashcards(
    flashcards: List[Dict[str, str]],
) -> bytes:
    mem_stream = io.StringIO()
    writer = csv.writer(mem_stream)
    writer.writerow(["Front", "Back"])
    for card in flashcards:
        writer.writerow([card["front"], card["back"]])
    return mem_stream.getvalue().encode("utf-8")


def create_json_from_flashcards(
    flashcards: List[Dict[str, str]],
) -> bytes:
    payload = {
        "deck_name": "CardifyAI Deck",
        "cards": flashcards,
    }
    return json.dumps(payload, indent=2).encode("utf-8")
