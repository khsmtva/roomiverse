"""
Инициализация файла SQLite для ROOMIVERSE 
"""

from sqlalchemy import text
from flask import Flask
from models import db


def create_app() -> Flask:
    # отдельный factory для утилит и миграций
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///roomiverse.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _migrate_sqlite_players_session_sid() -> None:
    try:
        # проверка наличия колонки для старых баз
        with db.engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(players)")).fetchall()
            col_names = {r[1] for r in rows}
            if "session_sid" not in col_names:
                conn.execute(text("ALTER TABLE players ADD COLUMN session_sid VARCHAR(64)"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_players_session_sid ON players (session_sid)"
                    )
                )
    except Exception as exc:
        print("Миграция:", exc)


def main() -> None:
    app = create_app()
    with app.app_context():
        # создание таблиц перед запуском сервера
        db.create_all()
        _migrate_sqlite_players_session_sid()
        print("Готово. Файл: roomiverse.db в папке запуска.")
        print("Дальше: python app.py")


if __name__ == "__main__":
    main()
