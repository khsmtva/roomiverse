from flask import Flask, render_template, request, jsonify, redirect
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy import text

import random
import string

from games.XO import TicTacToeGame
from models import db
from db_service import get_top_players, persist_finished_tic_tac_toe

app = Flask(__name__)
app.config["SECRET_KEY"] = "roomiverse-secret"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///roomiverse.db"
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
rooms = {}  # {код_комнаты: {players: [], scores: {}, game: None, game_type: ''}}
players = {}  # {sid: {name: '', room: '', xo_role: None}}


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
    """Страница игры"""
    return render_template("XO.html", room_code=room_code.strip().upper())


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

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})

    room = rooms[room_code]

    if len(room["players"]) < 2:
        return jsonify({"success": False, "message": "Нужно минимум 2 игрока"})

    player1 = room["players"][0]["name"]
    player2 = room["players"][1]["name"]

    players_list = [{"id": "p1", "name": player1}, {"id": "p2", "name": player2}]

    if game_type == "tic_tac_toe":
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
    return jsonify({"success": False, "message": "Неизвестный тип игры"})


@app.route("/api/game_state/<room_code>")
def game_state(room_code):
    """Состояние игры; ?sid= — чтобы вернуть your_player_id (p1/p2) для этого клиента."""
    if room_code not in rooms:
        return jsonify({"error": "Игра не найдена"}), 404

    room = rooms[room_code]
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


@app.route("/api/new_game/<room_code>", methods=["POST"])
def new_game(room_code):
    """Новая партия для тех же двух игроков (без перезагрузки страницы)."""
    data = request.json or {}
    sid = data.get("sid")

    if room_code not in rooms:
        return jsonify({"success": False, "message": "Комната не найдена"})

    room = rooms[room_code]
    if not room.get("game"):
        return jsonify({"success": False, "message": "Игра не начата"})

    if not sid or sid not in players or players[sid].get("room") != room_code:
        return jsonify({"success": False, "message": "Сессия не распознана"})

    if players[sid].get("xo_role") not in ("p1", "p2"):
        return jsonify({"success": False, "message": "Только игроки партии могут начать заново"})

    if len(room["players"]) < 2:
        return jsonify({"success": False, "message": "Недостаточно игроков"})

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
    print(f"✅ Клиент подключился: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    print(f"❌ Клиент отключился: {request.sid}")

    if request.sid in players:
        player = players[request.sid]
        room_code = player["room"]

        if room_code in rooms:
            rooms[room_code]["players"] = [
                p for p in rooms[room_code]["players"] if p["sid"] != request.sid
            ]

            socketio.emit(
                "players_update",
                {"players": [p["name"] for p in rooms[room_code]["players"]]},
                room=room_code,
                include_self=True,
            )

            if len(rooms[room_code]["players"]) == 0:
                del rooms[room_code]
                print(f"🚪 Комната {room_code} удалена")

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

    join_room(room_code)

    # Убираем старую запись этого же подключения, чтобы лобби+игра не дублировали игрока
    rooms[room_code]["players"] = [
        p for p in rooms[room_code]["players"] if p["sid"] != request.sid
    ]

    players[request.sid] = {
        "name": player_name,
        "room": room_code,
        "xo_role": None,
    }

    rooms[room_code]["players"].append({"sid": request.sid, "name": player_name})

    if rooms[room_code].get("game"):
        assign_xo_roles(room_code)

    if player_name not in rooms[room_code]["scores"]:
        rooms[room_code]["scores"][player_name] = 0

    # include_self=True: иначе отправитель не получает своё же событие (чат/список «молчат»)
    socketio.emit(
        "players_update",
        {"players": [p["name"] for p in rooms[room_code]["players"]]},
        room=room_code,
        include_self=True,
    )

    emit(
        "joined_room",
        {
            "room_code": room_code,
            "players": [p["name"] for p in rooms[room_code]["players"]],
        },
    )


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

        socketio.emit(
            "new_message",
            {"sender": player_name, "message": message, "time": "сейчас"},
            room=room_code,
            include_self=True,
        )


# ========== ЗАПУСК ==========

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 ROOMIVERSE - СЕРВЕР ЗАПУЩЕН")
    print("=" * 60)
    print("📱 Главная страница: http://localhost:5000")
    print("=" * 60 + "\n")
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)
