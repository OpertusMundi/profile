from . import db


def create_app():
    from geoprofile import app
    return app.app
