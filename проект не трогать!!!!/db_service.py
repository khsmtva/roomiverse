from datetime import datetime

from models import Game, GameParticipant, Player, Room, db


WIN_POINTS = 10
LOSS_POINTS = 0
DRAW_POINTS = 0


def _stable_player_key(source: dict | None, fallback_sid: str | None = None) -> str | None:
    """Ключ из join_room: client_id (sessionStorage), иначе socket sid."""
    if source:
        cid = (source.get("client_id") or "").strip()
        if cid:
            return cid
        sid = source.get("sid")
        if sid:
            return sid
    if fallback_sid:
        return fallback_sid
    return None


def ensure_player(nickname: str, stable_player_key: str | None = None) -> Player:
    """
    Игрок привязан к стабильному ключу клиента (client_id из лобби), колонка БД — session_sid.
    Так рейтинг накапливается при переподключении; разные люди с одним ником не сливаются.
    """
    nickname = (nickname or "Игрок").strip()[:20]
    if len(nickname) < 2:
        nickname = "Игрок"

    if stable_player_key:
        existing = Player.query.filter_by(session_sid=stable_player_key).first()
        if existing is not None:
            if existing.nickname != nickname:
                existing.nickname = nickname
            return existing

    player = Player(nickname=nickname, session_sid=stable_player_key, rating=0)
    db.session.add(player)
    db.session.flush()
    return player


def ensure_db_room(room_code: str, owner_player_id: int) -> Room:
    room = Room.query.filter_by(code=room_code).first()
    if room is not None:
        return room
    room = Room(code=room_code, owner_player_id=owner_player_id, status="in_game")
    db.session.add(room)
    db.session.flush()
    return room


def persist_finished_tic_tac_toe(
    room_code: str,
    player_slots: list[dict],
    game,
) -> None:
    """
    Сохраняет завершённую партию: дата, тип, участники, победитель; рейтинг +10 победителю, при поражении без изменений, ничья 0.
    player_slots: [{'sid': ..., 'name': ...}, ...] — первые два места = p1 / p2.
    """
    if not game.game_over or len(player_slots) < 2:
        return

    p1 = ensure_player(player_slots[0]["name"], _stable_player_key(player_slots[0]))
    p2 = ensure_player(player_slots[1]["name"], _stable_player_key(player_slots[1]))
    db_room = ensure_db_room(room_code, p1.id)

    winner_pid = None
    if game.winner:
        idx = 0 if game.winner["id"] == "p1" else 1
        slot = player_slots[idx]
        winner_pid = ensure_player(slot["name"], _stable_player_key(slot)).id

    g = Game(
        room_id=db_room.id,
        game_type="tic_tac_toe",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        winner_player_id=winner_pid,
        metadata_json=None,
    )
    db.session.add(g)
    db.session.flush()

    apply_game_result(g.id, winner_pid, [p1.id, p2.id])
    db.session.commit()


def persist_finished_game(
    room_code: str,
    game_type: str,
    participants: list[dict],
    winner_sid: str | None,
    tie: bool = False,
    metadata_json: str | None = None,
) -> None:
    """
    Универсальное сохранение результата игры с обновлением рейтинга.
    participants: [{"sid": "...", "name": "..."}]
    """
    if not participants:
        return

    first_player = ensure_player(
        participants[0]["name"],
        _stable_player_key(participants[0]),
    )
    db_room = ensure_db_room(room_code, first_player.id)

    participant_ids: list[int] = []
    sid_to_player_id: dict[str, int] = {}
    for item in participants:
        p = ensure_player(item["name"], _stable_player_key(item))
        participant_ids.append(p.id)
        sid_to_player_id[item["sid"]] = p.id

    winner_pid = None if tie else sid_to_player_id.get(winner_sid or "")
    game = Game(
        room_id=db_room.id,
        game_type=game_type,
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        winner_player_id=winner_pid,
        metadata_json=metadata_json,
    )
    db.session.add(game)
    db.session.flush()

    apply_game_result(game.id, winner_pid, participant_ids)
    db.session.commit()


def apply_game_result(game_id: int, winner_player_id: int | None, participant_ids: list[int]) -> None:
    """
    Правила рейтинга:
    - +10 победителю
    - при поражении рейтинг не меняется
    - ничья — без изменений
    """
    if not participant_ids:
        return

    for player_id in participant_ids:
        player = db.session.get(Player, player_id)
        if player is None:
            continue

        if winner_player_id is None:
            result = "draw"
            delta = DRAW_POINTS
        elif player_id == winner_player_id:
            result = "win"
            delta = WIN_POINTS
        else:
            result = "loss"
            delta = LOSS_POINTS

        participant = GameParticipant(
            game_id=game_id,
            player_id=player_id,
            result=result,
            score_delta=delta,
        )
        db.session.add(participant)
        player.rating += delta


def get_top_players(limit: int = 10) -> list[Player]:
    """
    Returns rating table (top players).
    """
    return (
        Player.query.order_by(Player.rating.desc(), Player.created_at.asc())
        .limit(limit)
        .all()
    )


def add_rating_points_for_session(
    nickname: str,
    points: int,
    stable_player_key: str | None,
) -> int:
    """
    Начисляет очки игроку по стабильному client_id (или fallback-ключу).
    Возвращает новый рейтинг.
    """
    player = ensure_player(nickname=nickname, stable_player_key=stable_player_key)
    player.rating += int(points)
    db.session.commit()
    return player.rating
