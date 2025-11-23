from flask.cli import with_appcontext
import click

from app import create_app, db

app = create_app()


@click.command("db_init")
@with_appcontext
def db_init():
    """Drop all tables and recreate them."""
    db.drop_all()
    db.create_all()
    click.echo("Database initialized.")


app.cli.add_command(db_init)


if __name__ == "__main__":
    app.run(debug=True)
