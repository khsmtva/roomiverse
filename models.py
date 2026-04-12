from datetime import datetime
from enum import Enum

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint

db = SQLAlchemy()


class RoomStatus(str, Enum):
    LOBBY = "lobby"
    IN_GAME = "in_game"
    CLOSED = "closed"


class GameType(str, Enum):
    TIC_TAC_TOE = "tic_tac_toe"
    GUESS_WORD = "guess_word"
    BATTLESHIP = "battleship"


class GameResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


class Player(db.Model):
    __tablename__ = "players"

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(20), nullable=False, index=True)
    # Различение игроков с одинаковым именем по сессии (ТЗ 3.5)
    session_sid = db.Column(db.String(64), nullable=True, unique=True, index=True)
    rating = db.Column(db.Integer, nullable=False, default=0, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        CheckConstraint("length(nickname) >= 2", name="ck_players_nickname_min_len"),
        CheckConstraint("length(nickname) <= 20", name="ck_players_nickname_max_len"),
    )


class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), nullable=False, unique=True, index=True)
    owner_player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=RoomStatus.LOBBY.value)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("length(code) = 6", name="ck_rooms_code_len"),
        CheckConstraint(
            "status in ('lobby', 'in_game', 'closed')",
            name="ck_rooms_status",
        ),
    )


class RoomSession(db.Model):
    __tablename__ = "room_sessions"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)
    session_sid = db.Column(db.String(64), nullable=False, index=True)
    player_id = db.Column(
        db.Integer,
        db.ForeignKey("players.id"),
        nullable=False,
        index=True,
    )
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    left_at = db.Column(db.DateTime, nullable=True)
    is_owner = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("room_id", "session_sid", name="uq_room_sid"),
    )


class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)
    game_type = db.Column(db.String(20), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True, index=True)
    winner_player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "game_type in ('tic_tac_toe', 'guess_word', 'battleship')",
            name="ck_games_type",
        ),
    )


class GameParticipant(db.Model):
    __tablename__ = "game_participants"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False, index=True)
    result = db.Column(db.String(10), nullable=True)
    score_delta = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_game_player"),
        CheckConstraint(
            "result is null or result in ('win', 'loss', 'draw')",
            name="ck_participants_result",
        ),
    )


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True, index=True)
    sender_name = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        CheckConstraint(
            "length(sender_name) >= 2 and length(sender_name) <= 20",
            name="ck_chat_sender_name_len",
        ),
    )
