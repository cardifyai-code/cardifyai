# manage.py (root)

import click
from flask.cli import with_appcontext

from app import create_app, db

app = create_app()


@click.command("db_init")
@with_appcontext
def db_init():
    """Drop all tables and recreate them (DANGEROUS – use carefully)."""
    db.drop_all()
    db.create_all()
    click.echo("Database initialized.")


# Register CLI command
app.cli.add_command(db_init)

if __name__ == "__main__":
    app.run(debug=True)
