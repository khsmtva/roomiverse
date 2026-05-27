"""
Модели SQLAlchemy для Roomiverse: игроки, комнаты, игры, чат.
"""
from datetime import datetime
from enum import Enum

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint

db = SQLAlchemy()  # создаём объект для работы с бд


class RoomStatus(str, Enum):
    """статусы комнаты в бд"""
    LOBBY = "lobby"      # ожидание игроков
    IN_GAME = "in_game"  # идёт игра
    CLOSED = "closed"    # комната закрыта


class GameType(str, Enum):
    """типы игр, поддерживаемые схемой бд"""
    TIC_TAC_TOE = "tic_tac_toe"   # крестики-нолики
    GUESS_WORD = "guess_word"     # угадай слово
    BATTLESHIP = "battleship"     # морской бой


class GameResult(str, Enum):
    """результат участника в партии"""
    WIN = "win"    # победа
    LOSS = "loss"  # поражение
    DRAW = "draw"  # ничья


class Player(db.Model):
    """модель игрока - хранит профили пользователей"""
    __tablename__ = "players"  # имя таблицы в бд

    id = db.Column(db.Integer, primary_key=True)  # уникальный идентификатор игрока
    nickname = db.Column(db.String(20), nullable=False, index=True)  # никнейм (индекс для быстрого поиска)
    # стабильный ключ игрока для склейки сессий
    session_sid = db.Column(db.String(64), nullable=True, unique=True, index=True)  # идентификатор сессии
    rating = db.Column(db.Integer, nullable=False, default=0, index=True)  # рейтинг игрока
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # дата регистрации
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,  # автоматически обновляется при изменении
    )

    __table_args__ = (
        CheckConstraint("length(nickname) >= 2", name="ck_players_nickname_min_len"),  # ник не короче 2 символов
        CheckConstraint("length(nickname) <= 20", name="ck_players_nickname_max_len"),  # ник не длиннее 20 символов
    )


class Room(db.Model):
    """модель комнаты - игровое пространство для группы игроков"""
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)  # уникальный идентификатор комнаты
    code = db.Column(db.String(6), nullable=False, unique=True, index=True)  # 6-символьный код для входа
    owner_player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)  # создатель комнаты
    # статус комнаты в цикле жизни матча
    status = db.Column(db.String(20), nullable=False, default=RoomStatus.LOBBY.value)  # текущий статус
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # время создания
    closed_at = db.Column(db.DateTime, nullable=True)  # время закрытия (если закрыта)

    __table_args__ = (
        CheckConstraint("length(code) = 6", name="ck_rooms_code_len"),  # код строго 6 символов
        CheckConstraint(
            "status in ('lobby', 'in_game', 'closed')",
            name="ck_rooms_status",  # допустимые значения статуса
        ),
    )


class RoomSession(db.Model):
    """модель сессии в комнате - история входов/выходов игроков"""
    __tablename__ = "room_sessions"

    id = db.Column(db.Integer, primary_key=True)  # уникальный идентификатор записи
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)  # id комнаты
    session_sid = db.Column(db.String(64), nullable=False, index=True)  # id сессии сокета
    player_id = db.Column(
        db.Integer,
        db.ForeignKey("players.id"),
        nullable=False,
        index=True,
    )  # id игрока
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # время входа
    left_at = db.Column(db.DateTime, nullable=True)  # время выхода (null если ещё в комнате)
    is_owner = db.Column(db.Boolean, nullable=False, default=False)  # является ли владельцем комнаты

    __table_args__ = (
        UniqueConstraint("room_id", "session_sid", name="uq_room_sid"),  # нельзя дважды зайти в комнату с одной сессией
    )


class Game(db.Model):
    """модель игры - запись о проведённой партии"""
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)  # уникальный идентификатор игры
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)  # в какой комнате играли
    game_type = db.Column(db.String(20), nullable=False, index=True)  # тип игры (tic_tac_toe, guess_word, battleship)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # время начала
    ended_at = db.Column(db.DateTime, nullable=True, index=True)  # время окончания (null если ещё идёт)
    winner_player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)  # победитель (null если ничья)
    metadata_json = db.Column(db.Text, nullable=True)  # дополнительная информация в формате json

    __table_args__ = (
        CheckConstraint(
            "game_type in ('tic_tac_toe', 'guess_word', 'battleship')",
            name="ck_games_type",  # допустимые типы игр
        ),
    )


class GameParticipant(db.Model):
    """модель участника игры - рейтинговые изменения за партию"""
    __tablename__ = "game_participants"

    id = db.Column(db.Integer, primary_key=True)  # уникальный идентификатор
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False, index=True)  # id игры
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False, index=True)  # id игрока
    result = db.Column(db.String(10), nullable=True)  # результат (win/loss/draw), null если ещё не завершена
    # изменение рейтинга за завершенную игру
    score_delta = db.Column(db.Integer, nullable=False, default=0)  # изменение рейтинга (+10, 0, или другое)

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_game_player"),  # игрок может участвовать в игре только раз
        CheckConstraint(
            "result is null or result in ('win', 'loss', 'draw')",
            name="ck_participants_result",  # допустимые значения результата
        ),
    )


class ChatMessage(db.Model):
    """модель сообщения чата - переписка в комнате"""
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)  # уникальный идентификатор сообщения
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)  # в какой комнате отправлено
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True, index=True)  # кто отправил (null для системных)
    sender_name = db.Column(db.String(20), nullable=False)  # имя отправителя (денормализация для быстрых запросов)
    content = db.Column(db.Text, nullable=False)  # текст сообщения
    is_system = db.Column(db.Boolean, nullable=False, default=False)  # true - системное сообщение, false - от игрока
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)  # время отправки

    __table_args__ = (
        CheckConstraint(
            "length(sender_name) >= 2 and length(sender_name) <= 20",
            name="ck_chat_sender_name_len",  # проверка длины имени отправителя
        ),
    )
