from app import create_app, db
from flask.cli import with_appcontext
import click

# Create the Flask application
app = create_app()

@click.command("db_init")
@with_appcontext
def db_init():
    """Drop all tables and recreate them."""
    db.drop_all()
    db.create_all()
    click.echo("Database initialized.")

# Register the CLI command
app.cli.add_command(db_init)


if __name__ == "__main__":
    # Local development server
    app.run(host="0.0.0.0", port=5000, debug=True)
