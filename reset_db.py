"""
Полная очистка таблиц SQLite (рейтинг, комнаты, игры, чат).

Остановите сервер (`python app.py`), иначе SQLite может ответить «database is locked».
Из папки проекта: python reset_db.py
"""

from app import app, db, _migrate_sqlite_players_session_sid


def main() -> None:
    with app.app_context():
        db.drop_all()
        db.create_all()
        _migrate_sqlite_players_session_sid()
        print("База очищена и пересоздана.")


if __name__ == "__main__":
    main()
