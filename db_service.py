from datetime import datetime

from models import Game, GameParticipant, Player, Room, db


WIN_POINTS = 10
LOSS_POINTS = -5
DRAW_POINTS = 0


def ensure_player(nickname: str, session_sid: str | None = None) -> Player:
    """
    Игрок привязан к сессии (sid), чтобы разные люди с одним ником не сливались в рейтинге (ТЗ 3.5).
    """
    nickname = (nickname or "Игрок").strip()[:20]
    if len(nickname) < 2:
        nickname = "Игрок"

    if session_sid:
        existing = Player.query.filter_by(session_sid=session_sid).first()
        if existing is not None:
            if existing.nickname != nickname:
                existing.nickname = nickname
            return existing

    player = Player(nickname=nickname, session_sid=session_sid, rating=0)
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
    Сохраняет завершённую партию: дата, тип, участники, победитель; обновляет рейтинг (+10 / -5 / 0).
    player_slots: [{'sid': ..., 'name': ...}, ...] — первые два места = p1 / p2.
    """
    if not game.game_over or len(player_slots) < 2:
        return

    p1 = ensure_player(player_slots[0]["name"], player_slots[0]["sid"])
    p2 = ensure_player(player_slots[1]["name"], player_slots[1]["sid"])
    db_room = ensure_db_room(room_code, p1.id)

    winner_pid = None
    if game.winner:
        idx = 0 if game.winner["id"] == "p1" else 1
        winner_pid = ensure_player(player_slots[idx]["name"], player_slots[idx]["sid"]).id

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


def apply_game_result(game_id: int, winner_player_id: int | None, participant_ids: list[int]) -> None:
    """
    Applies TЗ rating rules:
    - +10 for winner
    - -5 for each loser
    - draw -> no rating changes
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
