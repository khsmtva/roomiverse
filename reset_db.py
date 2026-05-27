#для полной пересборки (сброса) базы данных
from app import app, db, _migrate_sqlite_players_session_sid

def main() -> None:
    with app.app_context():
        # полная пересборка структуры базы
        db.drop_all()
        db.create_all()
        # возврат совместимости для старого формата данных
        _migrate_sqlite_players_session_sid()
        print("База очищена и пересоздана.")


if __name__ == "__main__":
    main()
