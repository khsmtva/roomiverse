"""
Инициализация файла SQLite для ROOMIVERSE (схема из models.py).

Как пользоваться:
  1) Установите зависимости: pip install -r requirements.txt
  2) Из папки проекта выполните: python init_db.py
     Создаётся файл roomiverse.db в текущей директории.

При обычном запуске сервера (python app.py) таблицы создаются автоматически
(db.create_all + лёгкая миграция для колонки session_sid у старых БД).

Файл БД: sqlite:///roomiverse.db (лежит рядом с app.py, если запускаете оттуда).
"""

from sqlalchemy import text

from flask import Flask

from models import db


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///roomiverse.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _migrate_sqlite_players_session_sid() -> None:
    try:
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
        db.create_all()
        _migrate_sqlite_players_session_sid()
        print("Готово. Файл: roomiverse.db в папке запуска.")
        print("Дальше: python app.py")


if __name__ == "__main__":
    main()
