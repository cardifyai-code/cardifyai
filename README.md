# AnkifyAI SaaS (Lite)

A simple SaaS-style web app where students can:
- Upload text or a PDF
- Generate high-quality flashcards using OpenAI
- Download their deck as:
  - `.apkg` for Anki
  - `.csv` for Quizlet
  - `.json` for Noji or custom importers

## 1. Features

- User accounts (email + password)
- Simple dashboard to generate decks
- Uses OpenAI to turn raw text into Q/A flashcards
- Exports:
  - `deck.apkg` (Anki via `genanki`)
  - `deck.csv` (Quizlet-style)
  - `deck.json` (generic)

## 2. Tech Stack

- Python 3.10+
- Flask
- SQLite (via SQLAlchemy)
- OpenAI API
- genanki for `.apkg` generation

## 3. Setup

1. Create and activate a virtualenv (optional but recommended):

   ```bash
   python -m venv .venv
   source .venv/bin/activate     # Linux/Mac
   .venv\Scripts\activate      # Windows
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root:

   ```bash
   OPENAI_API_KEY=your_openai_api_key_here
   FLASK_SECRET_KEY=change_me_to_something_random
   FLASK_ENV=development
   ```

4. Initialize the database:

   ```bash
   flask --app app.main db_init
   ```

5. Run the app:

   ```bash
   flask --app app.main run
   ```

   Then go to: http://127.0.0.1:5000

## 4. Environment Variables

Required:

- `OPENAI_API_KEY` — from your OpenAI account
- `FLASK_SECRET_KEY` — any random string, used for sessions & security

Optional:

- `OPENAI_MODEL` — defaults to `gpt-4.1-mini`. You can override it:
  - `o1-mini`
  - `gpt-4.1`
  - etc.

## 5. Notes

- This is a minimal but complete app. You can deploy it to Render, Railway,
  Fly.io, or any VPS.
- Stripe / billing is **not** wired in yet — you can put the app behind
  a paywall (e.g., LemonSqueezy license, gated login, etc.).
