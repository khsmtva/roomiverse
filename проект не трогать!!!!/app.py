import os
from datetime import datetime
import time

from flask import Flask, render_template, request, jsonify, redirect, send_file
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy import text

import random
import string

from games.XO import TicTacToeGame
try:
    from games.battleship import BattleshipGame
except Exception as battleship_import_error:
    BattleshipGame = None
from models import db
from db_service import (
    add_rating_points_for_session,
    get_top_players,
    persist_finished_tic_tac_toe,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "roomiverse-secret"
db_url = os.getenv("DATABASE_URL", "").strip()
if not db_url:
    # Локально запускаем SQLite, чтобы приложение всегда поднималось без внешней БД.
    db_url = "sqlite:///roomiverse.db"
elif db_url.startswith("postgres://"):
    # Совместимость старого формата URL от некоторых платформ
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")


def _migrate_sqlite_players_session_sid() -> None:
    """Старая БД без session_sid ломает запросы — добавляем колонку."""
    try:
        with db.engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(players)")).fetchall()
            col_names = {r[1] for r in rows}
            if "session_sid" not in col_names:
                conn.execute(text("ALTER TABLE players ADD COLUMN session_sid VARCHAR(64)"))
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS ix_players_session_sid ON players (session_sid)")
                )
    except Exception as exc:
        print(f"Примечание по миграции БД (можно игнорировать на первом запуске): {exc}")


with app.app_context():
    db.create_all()
    _migrate_sqlite_players_session_sid()

# Хранилище данных
rooms = {}  # {код_комнаты: {players: [], scores: {sid: int}, game: None, game_type: ''}}
players = {}  # {sid: {name: '', room: '', xo_role: None}}

_MSG_TWO_PLAYER_EXACT = (
    "Для этой игры в комнате должно быть ровно 2 игрока (не больше и не меньше)."
)


def _drop_player_from_room(room_code: str, client_id: str, old_sid: str | None = None) -> None:
    room = rooms.get(room_code)
    if not room:
        return
    room["players"] = [p for p in room["players"] if p.get("client_id") != client_id]
    room.get("pending_disconnects", {}).pop(client_id, None)
    room.get("client_to_sid", {}).pop(client_id, None)
    if old_sid:
        room.get("scores", {}).pop(old_sid, None)
    if room.get("created_by_client_id") == client_id:
        if room["players"]:
            new_host = room["players"][0]
            room["created_by_client_id"] = new_host.get("client_id")
            room["created_by_sid"] = new_host.get("sid")
            room["created_by"] = new_host.get("name")
        else:
            room["created_by_client_id"] = None
            room["created_by_sid"] = None
            room["created_by"] = ""


def _prune_disconnected(room_code: str) -> None:
    room = rooms.get(room_code)
    if not room:
        return
    pending = room.get("pending_disconnects", {})
    if not pending:
        return
    now = time.monotonic()
    expired = [cid for cid, deadline in pending.items() if deadline <= now]
    for client_id in expired:
        old_sid = room.get("client_to_sid", {}).get(client_id)
        if old_sid in players:
            del players[old_sid]
        _drop_player_from_room(room_code, client_id, old_sid=old_sid)

def generate_room_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def assign_xo_roles(room_code: str) -> None:
    """Первые два участника в списке — p1 (X) и p2 (O)."""
    room = rooms.get(room_code)
    if not room:
        return
    for p in room["players"]:
        sid = p["sid"]
        if sid in players:
            players[sid]["xo_role"] = None
    for i, p in enumerate(room["players"][:2]):
        sid = p["sid"]
        role = "p1" if i == 0 else "p2"
        if sid in players:
            players[sid]["xo_role"] = role


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/lobby")
def lobby():
    """Лобби с параметром ?code=..."""
    room_code = request.args.get("code")
    if not room_code:
        return redirect("/")
    room_code = room_code.strip().upper()
    return render_template("lobby.html", room_code=room_code)


@app.route("/game/<room_code>")
def game_page(room_code):
    """Страница игры по активному типу комнаты."""
    normalized_code = room_code.strip().upper()
    room = rooms.get(normalized_code)
    if room and room.get("game_type") == "goblin":
        return render_template("GOBLIN.html", room_code=normalized_code)
    if room and room.get("game_type") == "fifteen":
        return render_template("FIFTEEN.html", room_code=normalized_code)
    if room and room.get("game_type") == "space_race":
        return render_template("SPACE_RACE.html", room_code=normalized_code)
    if room and room.get("game_type") == "sea_battle":
        return render_template("BATTLESHIP.html", room_code=normalized_code)
    if room and room.get("game_type") == "flappy_bird":
        return render_template("FLAPPY_BIRD.html", room_code=normalized_code)
    if room and room.get("game_type") == "tower":
        return render_template("TOWER.html", room_code=normalized_code)
    return render_template("XO.html", room_code=normalized_code)


@app.route("/goblin/local")
def goblin_local_file():
    """
    Отдаем пользовательский HTML-файл игры ГОБЛИН внутри приложения.
    """
    return send_file("static/GoblinUser.html")


@app.route("/space/local")
def space_local_file():
    return send_file("static/SpaceRace.html")


@app.route("/flappy/local")
def flappy_local_file():
    return send_file("static/FlappyBird.html")


@app.route("/tower/local")
def tower_local_file():
    return send_file("static/TowerEmbed.html")


# ========== API ДЛЯ КОМНАТ ==========


@app.route("/api/create_room", methods=["POST"])
def create_room():
    data = request.json
    player_name = data.get("name", "Игрок")

    room_code = generate_room_code()
    while room_code in rooms:
        room_code = generate_room_code()

    rooms[room_code] = {
        "players": [],
        "scores": {},
        "created_by": player_name,
        "created_by_sid": None,
        "created_by_client_id": None,
        "chat_messages": [],
        "pending_disconnects": {},
        "client_to_sid": {},
        "game": None,
        "game_type": None,
        "xo_result_persisted": False,
    }

    return jsonify({"success": True, "room_code": room_code, "message": "Комната создана"})


@app.route("/api/join_room", methods=["POST"])
def join_room_api():
    data = request.json or {}
    room_code = (data.get("room_code") or "").strip().upper()

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})
    _prune_disconnected(room_code)

    if len(rooms[room_code]["players"]) >= 6:
        return jsonify({"success": False, "message": "В комнате нет свободных мест"})

    return jsonify({"success": True, "room_code": room_code, "message": "Подключение выполнено"})


@app.route("/api/rating/top")
def rating_top():
    try:
        rows = get_top_players(10)
        return jsonify(
            {
                "players": [
                    {"place": i + 1, "name": p.nickname, "rating": p.rating}
                    for i, p in enumerate(rows)
                ]
            }
        )
    except Exception as exc:
        print(f"/api/rating/top: {exc}")
        return jsonify({"players": []})


# ========== API ДЛЯ ИГР ==========


@app.route("/api/start_game/<room_code>", methods=["POST"])
def start_game(room_code):
    """Начать игру в комнате"""
    data = request.json or {}
    game_type = data.get("game_type", "tic_tac_toe")
    sid = data.get("sid")

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})

    _prune_disconnected(room_code)
    room = rooms[room_code]
    if not sid or sid not in players or players[sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Сессия не распознана. Обновите страницу."})

    if game_type == "tic_tac_toe":
        if len(room["players"]) != 2:
            return jsonify({"success": False, "message": _MSG_TWO_PLAYER_EXACT})

        player1 = room["players"][0]["name"]
        player2 = room["players"][1]["name"]
        players_list = [{"id": "p1", "name": player1}, {"id": "p2", "name": player2}]

        room["xo_result_persisted"] = False
        game = TicTacToeGame(room_code, players_list, board_size=9)
        room["game"] = game
        room["game_type"] = "tic_tac_toe"
        assign_xo_roles(room_code)

        socketio.emit(
            "game_started",
            {"game_type": "tic_tac_toe", "room_code": room_code},
            room=room_code,
        )

        return jsonify(
            {
                "success": True,
                "game_type": "tic_tac_toe",
                "game_state": game.get_board_state(),
            }
        )
    if game_type == "goblin":
        if len(room["players"]) < 1:
            return jsonify({"success": False, "message": "Нужен минимум 1 игрок"})
        room["game"] = None
        room["game_type"] = "goblin"
        room["result_persisted"] = False
        socketio.emit(
            "game_started",
            {"game_type": "goblin", "room_code": room_code},
            room=room_code,
        )
        return jsonify({"success": True, "game_type": "goblin"})
    if game_type == "fifteen":
        if len(room["players"]) != 2:
            return jsonify({"success": False, "message": _MSG_TWO_PLAYER_EXACT})
        room["game"] = None
        room["game_type"] = "fifteen"
        room["result_persisted"] = False
        socketio.emit(
            "game_started",
            {"game_type": "fifteen", "room_code": room_code},
            room=room_code,
        )
        return jsonify({"success": True, "game_type": "fifteen"})
    if game_type == "space_race":
        if len(room["players"]) < 1:
            return jsonify({"success": False, "message": "Нужен минимум 1 игрок"})
        room["game"] = None
        room["game_type"] = "space_race"
        room["result_persisted"] = False
        socketio.emit(
            "game_started",
            {"game_type": "space_race", "room_code": room_code},
            room=room_code,
        )
        return jsonify({"success": True, "game_type": "space_race"})
    if game_type == "sea_battle":
        if BattleshipGame is None:
            print(f"Модуль морского боя не загружен: {battleship_import_error}")
            return jsonify(
                {
                    "success": False,
                    "message": "Модуль 'Морской бой' недоступен на сервере. Проверьте деплой games/battleship.py.",
                }
            )
        if len(room["players"]) != 2:
            return jsonify({"success": False, "message": _MSG_TWO_PLAYER_EXACT})
        p1 = room["players"][0]
        p2 = room["players"][1]
        bs_players = [{"id": "p1", "name": p1["name"]}, {"id": "p2", "name": p2["name"]}]
        room["game"] = BattleshipGame(room_code, bs_players)
        room["game_type"] = "sea_battle"
        room["result_persisted"] = False
        room["battle_sid_to_pid"] = {p1["sid"]: "p1", p2["sid"]: "p2"}
        socketio.emit(
            "game_started",
            {"game_type": "sea_battle", "room_code": room_code},
            room=room_code,
        )
        return jsonify({"success": True, "game_type": "sea_battle"})
    if game_type == "flappy_bird":
        if len(room["players"]) < 1:
            return jsonify({"success": False, "message": "Нужен минимум 1 игрок"})
        room["game"] = None
        room["game_type"] = "flappy_bird"
        room["result_persisted"] = False
        socketio.emit(
            "game_started",
            {"game_type": "flappy_bird", "room_code": room_code},
            room=room_code,
        )
        return jsonify({"success": True, "game_type": "flappy_bird"})
    if game_type == "tower":
        if len(room["players"]) != 2:
            return jsonify({"success": False, "message": _MSG_TWO_PLAYER_EXACT})
        room["game"] = None
        room["game_type"] = "tower"
        room["result_persisted"] = False
        socketio.emit(
            "game_started",
            {"game_type": "tower", "room_code": room_code},
            room=room_code,
        )
        return jsonify({"success": True, "game_type": "tower"})
    return jsonify({"success": False, "message": "Неизвестный тип игры"})


@app.route("/api/game_state/<room_code>")
def game_state(room_code):
    """Состояние игры; ?sid= — чтобы вернуть your_player_id (p1/p2) для этого клиента."""
    if room_code not in rooms:
        return jsonify({"error": "Игра не найдена"}), 404

    _prune_disconnected(room_code)
    room = rooms[room_code]
    if room.get("game_type") == "goblin":
        return jsonify({"game": "goblin_embed"})
    if room.get("game_type") == "fifteen":
        return jsonify({"game": "fifteen"})
    if room.get("game_type") == "space_race":
        return jsonify({"game": "space_race"})
    if room.get("game_type") == "flappy_bird":
        return jsonify({"game": "flappy_bird"})
    if room.get("game_type") == "tower":
        return jsonify({"game": "tower_embed"})
    if room.get("game_type") == "sea_battle":
        sid = request.args.get("sid")
        pid = (room.get("battle_sid_to_pid") or {}).get(sid or "")
        if pid not in ("p1", "p2") and sid in players and players[sid].get("room") == room_code:
            # sid может измениться после перезагрузки вкладки; восстанавливаем роль по имени.
            current_name = players[sid].get("name")
            if room.get("game") and current_name:
                for p in room["game"].players:
                    if p.get("name") == current_name and p.get("id") in ("p1", "p2"):
                        pid = p["id"]
                        room.setdefault("battle_sid_to_pid", {})[sid] = pid
                        break
        if pid not in ("p1", "p2"):
            return jsonify({"error": "Вы не участник этой партии"}), 403
        return jsonify(room["game"].get_state_for_player(pid))

    if not room["game"]:
        return jsonify({"error": "Игра не начата"}), 404

    state = room["game"].get_board_state()
    sid = request.args.get("sid")
    if sid and sid in players and players[sid].get("room") == room_code:
        state["your_player_id"] = players[sid].get("xo_role")
    else:
        state["your_player_id"] = None
    return jsonify(state)


@app.route("/api/make_move", methods=["POST"])
def make_move():
    """Ход только от стороны, чья сейчас очередь и чей sid совпадает с ролью."""
    data = request.json or {}
    room_code = data.get("room_code")
    player_id = data.get("player_id")
    row = data.get("row")
    col = data.get("col")
    sid = data.get("sid")

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Игра не найдена"})

    _prune_disconnected(room_code)
    room = rooms[room_code]
    if not room["game"]:
        return jsonify({"success": False, "message": "Игра не начата"})

    if not sid or sid not in players or players[sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Сессия не распознана. Обновите страницу."})

    expected = players[sid].get("xo_role")
    if expected not in ("p1", "p2"):
        return jsonify({"success": False, "message": "Вы не участник этой партии"})

    if player_id != expected:
        return jsonify({"success": False, "message": "Неверная роль игрока"})

    if row is None or col is None:
        return jsonify({"success": False, "message": "Нет координат хода"})

    result = room["game"].make_move(player_id, int(row), int(col))

    if result.get("success") and result.get("game_state", {}).get("game_over"):
        if not room.get("xo_result_persisted"):
            try:
                persist_finished_tic_tac_toe(
                    room_code,
                    room["players"][:2],
                    room["game"],
                )
                room["xo_result_persisted"] = True
            except Exception as exc:
                print(f"Ошибка сохранения партии в БД: {exc}")

    return jsonify(result)


@app.route("/api/battleship/shoot", methods=["POST"])
def battleship_shoot():
    data = request.json or {}
    room_code = (data.get("room_code") or "").strip().upper()
    sid = data.get("sid")
    coord = data.get("coord")

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})
    _prune_disconnected(room_code)
    room = rooms[room_code]
    if room.get("game_type") != "sea_battle" or not room.get("game"):
        return jsonify({"success": False, "message": "Морской бой не запущен"})

    pid = (room.get("battle_sid_to_pid") or {}).get(sid or "")
    if pid not in ("p1", "p2") and sid in players and players[sid].get("room") == room_code:
        current_name = players[sid].get("name")
        if room.get("game") and current_name:
            for p in room["game"].players:
                if p.get("name") == current_name and p.get("id") in ("p1", "p2"):
                    pid = p["id"]
                    room.setdefault("battle_sid_to_pid", {})[sid] = pid
                    break
    if pid not in ("p1", "p2"):
        return jsonify({"success": False, "message": "Вы не участник этой партии"})

    result = room["game"].shoot(pid, coord)
    if result.get("success") and result.get("game_over") and not room.get("result_persisted"):
        winner_pid = result.get("winner", {}).get("id")
        for psid, pp in (room.get("battle_sid_to_pid") or {}).items():
            if pp != winner_pid:
                continue
            pmeta = players.get(psid, {})
            stable_key = pmeta.get("client_id") or psid
            add_rating_points_for_session(pmeta.get("name", "Игрок"), 10, stable_key)
            room["scores"][psid] = int(room["scores"].get(psid, 0)) + 10
        room["result_persisted"] = True

    return jsonify(result)


@app.route("/api/add_rating_points", methods=["POST"])
def add_rating_points():
    data = request.json or {}
    room_code = (data.get("room_code") or "").strip().upper()
    sid = data.get("sid")
    points = int(data.get("points") or 0)
    game_type = data.get("game_type")
    if points <= 0:
        return jsonify({"success": False, "message": "Очки должны быть больше нуля"})
    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})
    _prune_disconnected(room_code)
    room = rooms[room_code]
    if sid not in players or players[sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Сессия игрока не найдена"})
    if game_type and room.get("game_type") != game_type:
        return jsonify({"success": False, "message": "Неверный тип игры для комнаты"})

    room["scores"][sid] = int(room["scores"].get(sid, 0)) + points
    stable_key = players[sid].get("client_id") or sid
    rating = add_rating_points_for_session(players[sid]["name"], points, stable_key)
    return jsonify({"success": True, "rating": rating, "added": points})


@app.route("/api/finish_game", methods=["POST"])
def finish_game():
    data = request.json or {}
    room_code = (data.get("room_code") or "").strip().upper()
    winner_sid = data.get("winner_sid")
    game_type = data.get("game_type")
    moves = data.get("moves")

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})
    _prune_disconnected(room_code)
    room = rooms[room_code]
    if room.get("game_type") != game_type:
        return jsonify({"success": False, "message": "Игра в комнате не совпадает"})
    if game_type == "tower":
        return jsonify({"success": False, "message": "Победитель в Tower определяется автоматически"})
    if room.get("result_persisted"):
        return jsonify({"success": True, "message": "Результат уже сохранен"})
    if winner_sid not in players or players[winner_sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Победитель не найден в комнате"})

    if game_type == "fifteen" and len(room.get("players", [])) != 2:
        return jsonify({"success": False, "message": _MSG_TWO_PLAYER_EXACT})

    participants = [
        {"sid": p["sid"], "name": p["name"], "client_id": p.get("client_id")}
        for p in room.get("players", [])
    ]
    if len(participants) < 1:
        return jsonify({"success": False, "message": "Нет участников для подсчета"})

    try:
        for p in participants:
            if p["sid"] != winner_sid:
                continue
            room["scores"][p["sid"]] = int(room["scores"].get(p["sid"], 0)) + 10
            stable_key = (p.get("client_id") or "").strip() or p["sid"]
            add_rating_points_for_session(
                nickname=p["name"],
                points=10,
                stable_player_key=stable_key,
            )
        room["result_persisted"] = True
        return jsonify({"success": True})
    except Exception as exc:
        print(f"Ошибка сохранения результата {game_type}: {exc}")
        return jsonify({"success": False, "message": "Не удалось сохранить результат"})


def _tower_apply_loser_and_award(room_code: str, loser_sid: str) -> tuple[bool, str | None, str | None]:
    """Tower PvP: первый проигравший/сдавшийся — победа соперника (+10)."""
    room = rooms.get(room_code)
    if not room or room.get("game_type") != "tower":
        return False, None, "no_match"
    if room.get("result_persisted"):
        return False, None, "done"
    pl = room.get("players", [])
    if len(pl) != 2:
        return False, None, "players"
    s0, s1 = pl[0].get("sid"), pl[1].get("sid")
    if not s0 or not s1 or loser_sid not in (s0, s1):
        return False, None, "sid"
    winner_sid = s1 if loser_sid == s0 else s0
    if winner_sid not in players or loser_sid not in players:
        return False, None, "players_map"
    if players[winner_sid].get("room") != room_code or players[loser_sid].get("room") != room_code:
        return False, None, "room"
    try:
        winner_name = players[winner_sid]["name"]
        room["scores"][winner_sid] = int(room["scores"].get(winner_sid, 0)) + 10
        stable_key = players[winner_sid].get("client_id") or winner_sid
        add_rating_points_for_session(
            nickname=winner_name,
            points=10,
            stable_player_key=stable_key,
        )
        room["result_persisted"] = True
        return True, winner_sid, None
    except Exception as exc:
        print(f"Ошибка начисления Tower PvP: {exc}")
        return False, None, "db"


@app.route("/api/tower_surrender", methods=["POST"])
def tower_surrender():
    data = request.json or {}
    room_code = (data.get("room_code") or "").strip().upper()
    sid = data.get("sid")
    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})
    _prune_disconnected(room_code)
    room = rooms[room_code]
    if room.get("game_type") != "tower":
        return jsonify({"success": False, "message": "В комнате не Tower"})
    if not sid or sid not in players or players[sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Сессия не распознана"})
    ok, winner_sid, err = _tower_apply_loser_and_award(room_code, sid)
    if ok and winner_sid:
        socketio.emit(
            "tower_pvp_end",
            {"winner_sid": winner_sid, "loser_sid": sid, "reason": "surrender"},
            room=room_code,
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "message": err or "Нельзя сдаться сейчас"})


@app.route("/api/new_game/<room_code>", methods=["POST"])
def new_game(room_code):
    """Новая партия для тех же двух игроков (без перезагрузки страницы)."""
    data = request.json or {}
    sid = data.get("sid")

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})

    _prune_disconnected(room_code)
    room = rooms[room_code]
    if not room.get("game"):
        return jsonify({"success": False, "message": "Игра не начата"})

    if not sid or sid not in players or players[sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Сессия не распознана"})

    if players[sid].get("xo_role") not in ("p1", "p2"):
        return jsonify({"success": False, "message": "Только игроки партии могут начать заново"})

    if len(room["players"]) != 2:
        return jsonify({"success": False, "message": _MSG_TWO_PLAYER_EXACT})

    player1 = room["players"][0]["name"]
    player2 = room["players"][1]["name"]
    board_size = room["game"].board_size
    players_list = [{"id": "p1", "name": player1}, {"id": "p2", "name": player2}]

    room["game"] = TicTacToeGame(room_code, players_list, board_size=board_size)
    room["xo_result_persisted"] = False
    assign_xo_roles(room_code)

    state = room["game"].get_board_state()
    if sid in players and players[sid].get("room") == room_code:
        state["your_player_id"] = players[sid].get("xo_role")

    socketio.emit("xo_state_refresh", {}, room=room_code)

    return jsonify({"success": True, "game_state": state})


# ========== СОКЕТЫ ==========


@socketio.on("connect")
def handle_connect():
    print(f"Клиент подключился: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    print(f" Клиент отключился: {request.sid}")

    if request.sid not in players:
        return

    player = players[request.sid]
    room_code = player["room"]
    client_id = player.get("client_id")

    if room_code in rooms:
        if client_id:
            _drop_player_from_room(room_code, client_id, old_sid=request.sid)
        else:
            room = rooms[room_code]
            room["players"] = [p for p in room["players"] if p.get("sid") != request.sid]
            room.get("scores", {}).pop(request.sid, None)

        if room_code in rooms:
            room = rooms[room_code]
            socketio.emit(
                "players_update",
                {
                    "players": [p["name"] for p in room["players"]],
                    "host_sid": room.get("created_by_sid"),
                },
                room=room_code,
                include_self=True,
            )

            _prune_disconnected(room_code)
            # Не удалять комнату, если игра уже запущена: иначе при переходе лобби→игра
            # все сокеты отключаются, список участников пустеет и комната исчезает до GET /game/…
            # — тогда game_page не находит комнату и отдаёт крестики-нолики по умолчанию.
            if len(room["players"]) == 0 and not room.get("game_type"):
                del rooms[room_code]
                print(f"Комната {room_code} удалена")

    del players[request.sid]


@socketio.on("join_room")
def handle_join_room(data):
    if not data:
        emit("error", {"message": "Нет данных"})
        return

    room_code = (data.get("room_code") or "").strip().upper()
    raw_name = data.get("name")
    player_name = (raw_name if raw_name is not None else "").strip() or "Игрок"
    if len(player_name) < 2:
        player_name = "Игрок"
    if len(player_name) > 20:
        player_name = player_name[:20]

    if room_code not in rooms:
        emit("error", {"message": "Комната не найдена"})
        return

    _prune_disconnected(room_code)
    join_room(room_code)
    room = rooms[room_code]
    client_id = (data.get("client_id") or "").strip()
    if not client_id:
        client_id = request.sid

    old_sid = room.get("client_to_sid", {}).get(client_id)
    if old_sid and old_sid in players:
        del players[old_sid]
    room.setdefault("pending_disconnects", {}).pop(client_id, None)
    room.setdefault("client_to_sid", {})[client_id] = request.sid
    # Убираем старую запись текущего sid (редкий дубликат).
    room["players"] = [p for p in room["players"] if p.get("sid") != request.sid]

    players[request.sid] = {
        "name": player_name,
        "room": room_code,
        "client_id": client_id,
        "xo_role": None,
    }

    existing = next((p for p in room["players"] if p.get("client_id") == client_id), None)
    if existing:
        existing["sid"] = request.sid
        existing["name"] = player_name
    else:
        room["players"].append({"sid": request.sid, "name": player_name, "client_id": client_id})
    if not room.get("created_by_client_id"):
        room["created_by_client_id"] = client_id
        room["created_by_sid"] = request.sid
        room["created_by"] = player_name
    elif room.get("created_by_client_id") == client_id:
        room["created_by_sid"] = request.sid
        room["created_by"] = player_name
    if room.get("game_type") == "sea_battle":
        # При переподключении закрепляем новый sid за слотом игрока в Морском бою
        game = room.get("game")
        if game:
            for p in game.players:
                if p.get("name") == player_name and p.get("id") in ("p1", "p2"):
                    room.setdefault("battle_sid_to_pid", {})[request.sid] = p["id"]
                    break

    if room.get("game"):
        assign_xo_roles(room_code)

    if request.sid not in room["scores"]:
        room["scores"][request.sid] = 0

    # include_self=True: иначе отправитель не получает своё же событие (чат/список «молчат»)
    socketio.emit(
        "players_update",
        {
            "players": [p["name"] for p in room["players"]],
            "host_sid": room.get("created_by_sid"),
        },
        room=room_code,
        include_self=True,
    )

    emit(
        "joined_room",
        {
            "room_code": room_code,
            "players": [p["name"] for p in room["players"]],
            "host_sid": room.get("created_by_sid"),
            "is_host": room.get("created_by_sid") == request.sid,
        },
    )
    emit("chat_history", {"messages": room.get("chat_messages", [])[-100:]})


@socketio.on("send_message")
def handle_send_message(data):
    if not data:
        return
    room_code = (data.get("room_code") or "").strip().upper()
    message = (data.get("message") or "").strip()
    if not message or not room_code:
        return

    if request.sid in players:
        player_name = players[request.sid]["name"]
        room = rooms.get(room_code)
        if room is not None:
            room.setdefault("chat_messages", []).append({"sender": player_name, "message": message, "time": datetime.utcnow().isoformat()})
            if len(room["chat_messages"]) > 200:
                room["chat_messages"] = room["chat_messages"][-200:]

        socketio.emit(
            "new_message",
            {"sender": player_name, "message": message, "time": "сейчас"},
            room=room_code,
            include_self=True,
        )


@socketio.on("fifteen_timer_set")
def handle_fifteen_timer_set(data):
    if not data:
        return
    room_code = (data.get("room_code") or "").strip().upper()
    if room_code not in rooms:
        return
    room = rooms[room_code]
    if room.get("game_type") != "fifteen":
        return
    if request.sid not in players or players[request.sid].get("room") != room_code:
        return
    try:
        minutes = int(data.get("minutes"))
    except (TypeError, ValueError):
        return
    if minutes not in (3, 5, 7):
        return
    socketio.emit(
        "fifteen_timer_sync",
        {
            "room_code": room_code,
            "minutes": minutes,
            "from_sid": request.sid,
        },
        room=room_code,
        include_self=True,
    )


@socketio.on("tower_pvp_defeat")
def handle_tower_pvp_defeat(data):
    if not data:
        return
    room_code = (data.get("room_code") or "").strip().upper()
    if room_code not in rooms:
        return
    _prune_disconnected(room_code)
    ok, winner_sid, _err = _tower_apply_loser_and_award(room_code, request.sid)
    if ok and winner_sid:
        socketio.emit(
            "tower_pvp_end",
            {
                "winner_sid": winner_sid,
                "loser_sid": request.sid,
                "reason": "defeat",
            },
            room=room_code,
        )


# ========== ЗАПУСК ==========

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("ROOMIVERSE - СЕРВЕР ЗАПУЩЕН")
    print("=" * 60)
    print("Главная страница: http://localhost:5000")
    print("=" * 60 + "\n")
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)
