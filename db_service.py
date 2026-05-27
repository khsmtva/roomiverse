from datetime import datetime

from models import Game, GameParticipant, Player, Room, db


WIN_POINTS = 10  # очки за победу
LOSS_POINTS = 0  # очки за поражение (не меняется)
DRAW_POINTS = 0  # очки за ничью


def _stable_player_key(source: dict | None, fallback_sid: str | None = None) -> str | None:
    """ключ из join_room: client_id (sessionstorage), иначе socket sid."""
    if source:
        cid = (source.get("client_id") or "").strip()  # получаем client_id из словаря
        if cid:
            return cid  # приоритет у client_id (стабильный ключ)
        sid = source.get("sid")  # если нет client_id, берём sid
        if sid:
            return sid
    if fallback_sid:  # если source пустой, используем fallback
        return fallback_sid
    return None  # ключ не найден


def ensure_player(nickname: str, stable_player_key: str | None = None) -> Player:
    """
    игрок привязан к стабильному ключу клиента (client_id из лобби), колонка бд — session_sid.
    так рейтинг накапливается при переподключении; разные люди с одним ником не сливаются.
    """
    nickname = (nickname or "Игрок").strip()[:20]  # обрезаем ник до 20 символов
    if len(nickname) < 2:  # если ник слишком короткий
        nickname = "Игрок"  # заменяем на стандартное имя

    # поиск игрока по стабильному ключу сессии
    if stable_player_key:
        existing = Player.query.filter_by(session_sid=stable_player_key).first()  # ищем по session_sid
        if existing is not None:
            if existing.nickname != nickname:  # если ник изменился
                existing.nickname = nickname  # обновляем ник
            return existing  # возвращаем существующего игрока

    # создание нового профиля если в базе нет совпадения
    player = Player(nickname=nickname, session_sid=stable_player_key, rating=0)  # новый игрок с нулевым рейтингом
    db.session.add(player)  # добавляем в сессию
    db.session.flush()  # отправляем в бд (но не коммитим)
    return player


def ensure_db_room(room_code: str, owner_player_id: int) -> Room:
    """находит комнату по коду или создаёт новую"""
    room = Room.query.filter_by(code=room_code).first()  # ищем комнату в бд
    if room is not None:
        return room  # возвращаем существующую комнату
    room = Room(code=room_code, owner_player_id=owner_player_id, status="in_game")  # создаём новую
    db.session.add(room)  # добавляем в сессию
    db.session.flush()  # отправляем в бд
    return room


def persist_finished_tic_tac_toe(
    room_code: str,
    player_slots: list[dict],
    game,
) -> None:
    """
    сохраняет завершённую партию: дата, тип, участники, победитель; рейтинг +10 победителю, при поражении без изменений, ничья 0.
    player_slots: [{'sid': ..., 'name': ...}, ...] — первые два места = p1 / p2.
    """
    if not game.game_over or len(player_slots) < 2:  # если игра не закончена или меньше двух игроков
        return

    p1 = ensure_player(player_slots[0]["name"], _stable_player_key(player_slots[0]))  # создаём/находим первого игрока
    p2 = ensure_player(player_slots[1]["name"], _stable_player_key(player_slots[1]))  # создаём/находим второго игрока
    db_room = ensure_db_room(room_code, p1.id)  # создаём/находим комнату

    winner_pid = None
    if game.winner:  # если есть победитель
        idx = 0 if game.winner["id"] == "p1" else 1  # определяем индекс победителя (p1 или p2)
        slot = player_slots[idx]  # получаем данные победителя
        winner_pid = ensure_player(slot["name"], _stable_player_key(slot)).id  # создаём/находим победителя

    g = Game(
        room_id=db_room.id,  # id комнаты
        game_type="tic_tac_toe",  # тип игры
        started_at=datetime.utcnow(),  # время начала
        ended_at=datetime.utcnow(),  # время окончания
        winner_player_id=winner_pid,  # победитель (если есть)
        metadata_json=None,  # дополнительная информация (не используется)
    )
    db.session.add(g)  # добавляем игру
    db.session.flush()  # отправляем в бд

    apply_game_result(g.id, winner_pid, [p1.id, p2.id])  # применяем изменения рейтинга
    db.session.commit()  # фиксируем все изменения


def persist_finished_game(
    room_code: str,
    game_type: str,
    participants: list[dict],
    winner_sid: str | None,
    tie: bool = False,
    metadata_json: str | None = None,
) -> None:
    """
    универсальное сохранение результата игры с обновлением рейтинга.
    participants: [{"sid": "...", "name": "..."}]
    """
    if not participants:  # если нет участников
        return

    first_player = ensure_player(
        participants[0]["name"],  # имя первого участника
        _stable_player_key(participants[0]),  # стабильный ключ
    )
    db_room = ensure_db_room(room_code, first_player.id)  # создаём/находим комнату

    participant_ids: list[int] = []  # список id участников
    sid_to_player_id: dict[str, int] = {}  # маппинг socket_id -> player_id
    for item in participants:  # проходим по всем участникам
        p = ensure_player(item["name"], _stable_player_key(item))  # создаём/находим игрока
        participant_ids.append(p.id)  # добавляем id в список
        sid_to_player_id[item["sid"]] = p.id  # сохраняем соответствие sid -> player_id

    winner_pid = None if tie else sid_to_player_id.get(winner_sid or "")  # определяем победителя (если не ничья)
    game = Game(
        room_id=db_room.id,  # id комнаты
        game_type=game_type,  # тип игры
        started_at=datetime.utcnow(),  # время начала
        ended_at=datetime.utcnow(),  # время окончания
        winner_player_id=winner_pid,  # победитель
        metadata_json=metadata_json,  # доп. информация
    )
    db.session.add(game)  # добавляем игру
    db.session.flush()  # отправляем в бд

    apply_game_result(game.id, winner_pid, participant_ids)  # применяем изменения рейтинга
    db.session.commit()  # фиксируем все изменения


def apply_game_result(game_id: int, winner_player_id: int | None, participant_ids: list[int]) -> None:
    """
    правила рейтинга:
    - +10 победителю
    - при поражении рейтинг не меняется
    - ничья — без изменений
    """
    if not participant_ids:  # если нет участников
        return

    # начисление рейтинга всем участникам партии
    for player_id in participant_ids:  # проходим по всем участникам
        player = db.session.get(Player, player_id)  # получаем игрока из бд
        if player is None:  # если игрок не найден
            continue

        if winner_player_id is None:  # ничья
            result = "draw"
            delta = DRAW_POINTS
        elif player_id == winner_player_id:  # победитель
            result = "win"
            delta = WIN_POINTS
        else:  # проигравший
            result = "loss"
            delta = LOSS_POINTS

        participant = GameParticipant(
            game_id=game_id,  # id игры
            player_id=player_id,  # id игрока
            result=result,  # результат (win/loss/draw)
            score_delta=delta,  # изменение рейтинга
        )
        db.session.add(participant)  # добавляем запись об участии
        player.rating += delta  # обновляем рейтинг игрока


def get_top_players(limit: int = 10) -> list[Player]:
    """
    возвращает таблицу рейтинга (топ игроков).
    """
    return (
        Player.query.order_by(Player.rating.desc(), Player.created_at.asc())  # сортируем по убыванию рейтинга, потом по дате создания
        .limit(limit)  # ограничиваем количество
        .all()  # выполняем запрос
    )


def add_rating_points_for_session(
    nickname: str,
    points: int,
    stable_player_key: str | None,
) -> int:
    """
    начисляет очки игроку по стабильному client_id (или fallback-ключу).
    возвращает новый рейтинг.
    """
    player = ensure_player(nickname=nickname, stable_player_key=stable_player_key)  # создаём/находим игрока
    player.rating += int(points)  # добавляем очки к рейтингу
    db.session.commit()  # фиксируем изменения
    return player.rating  # возвращаем новый рейтинг
