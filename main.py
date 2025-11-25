# main.py (root)

from app import create_app

# Gunicorn / Render entrypoint
app = create_app()

if __name__ == "__main__":
    # Local dev only
    app.run(host="0.0.0.0", port=5000, debug=True)
