from flask import current_app as app


@app.cli.command()
def init_db():
    """Initialize database."""
    from geoprofile.database import db
    db.create_all()
