"""
Модуль игры "Морской бой" для двух игроков.
"""

import random
from typing import Any, Dict, List, Optional


class BattleshipGame:
    # размер стандартного поля морского боя
    BOARD_SIZE = 10  # размер игрового поля 10x10
    FLEET = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]  # состав флота: один 4-палубный, два 3-палубных, три 2-палубных, четыре 1-палубных
    LETTERS = "АБВГДЕЖЗИК"  # буквы для обозначения колонок (без Ё)

    def __init__(self, room_id: str, players: List[Dict[str, str]]) -> None:
        self.room_id = room_id  # идентификатор комнаты
        self.players = players[:2]  # берём первых двух игроков
        self.current_player_index = random.randint(0, 1)  # случайный выбор первого хода
        self.game_over = False  # флаг окончания игры
        self.winner: Optional[Dict[str, Any]] = None  # победитель (если есть)

        self.boards = [self._create_empty_board(), self._create_empty_board()]  # игровые поля с кораблями (для каждого игрока)
        self.shots = [self._create_empty_board(), self._create_empty_board()]  # поля выстрелов (куда уже стреляли)
        # раздельные наборы кораблей для каждого игрока
        self.ships: List[List[Dict[str, Any]]] = [[], []]  # список кораблей каждого игрока
        self._place_random_fleet(0)  # расставляем корабли для первого игрока
        self._place_random_fleet(1)  # расставляем корабли для второго игрока

    def _create_empty_board(self) -> List[List[str]]:
        """создаёт пустое игровое поле размером board_size x board_size"""
        return [[" " for _ in range(self.BOARD_SIZE)] for _ in range(self.BOARD_SIZE)]

    def _place_random_fleet(self, player_index: int) -> None:
        """случайным образом расставляет флот на поле игрока"""
        board = self.boards[player_index]  # поле текущего игрока
        ships: List[Dict[str, Any]] = []  # список кораблей
        for length in self.FLEET:  # для каждого размера корабля из состава флота
            placed = False  # флаг успешной расстановки
            for _ in range(300):  # пробуем до 300 раз
                horizontal = random.choice([True, False])  # ориентация: горизонтально или вертикально
                if horizontal:  # горизонтальная ориентация
                    row = random.randint(0, self.BOARD_SIZE - 1)  # случайная строка
                    col = random.randint(0, self.BOARD_SIZE - length)  # колонка с учётом длины
                    cells = [(row, col + i) for i in range(length)]  # координаты всех клеток корабля
                else:  # вертикальная ориентация
                    row = random.randint(0, self.BOARD_SIZE - length)  # строка с учётом длины
                    col = random.randint(0, self.BOARD_SIZE - 1)  # случайная колонка
                    cells = [(row + i, col) for i in range(length)]  # координаты всех клеток корабля
                if self._can_place_ship(board, cells):  # проверяем, можно ли поставить корабль
                    for r, c in cells:  # отмечаем клетки корабля на поле
                        board[r][c] = "S"  # S - ship (корабль)
                    ships.append({"cells": cells, "hits": set(), "size": length, "sunk": False})  # сохраняем корабль
                    placed = True
                    break
            if not placed:  # если не удалось расставить корабль за 300 попыток
                raise RuntimeError("Не удалось автоматически расставить все корабли")
        self.ships[player_index] = ships  # сохраняем все корабли игрока

    def _can_place_ship(self, board: List[List[str]], cells: List[tuple[int, int]]) -> bool:
        """проверяет, можно ли разместить корабль в указанных клетках (нет соседних кораблей)"""
        for r, c in cells:  # проходим по всем клеткам корабля
            if board[r][c] != " ":  # если клетка уже занята
                return False
            # проверяем соседние клетки (включая диагональные)
            for rr in range(max(0, r - 1), min(self.BOARD_SIZE, r + 2)):  # соседние строки
                for cc in range(max(0, c - 1), min(self.BOARD_SIZE, c + 2)):  # соседние колонки
                    if board[rr][cc] == "S":  # если рядом есть корабль
                        return False
        return True  # можно разместить

    def _public_view(self, viewer_index: int) -> Dict[str, Any]:
        """возвращает состояние игры с точки зрения указанного игрока"""
        enemy_index = 1 - viewer_index  # индекс соперника
        return {
            "your_board": self.boards[viewer_index],  # своё поле (с кораблями)
            "shots_board": self.shots[viewer_index],  # поле выстрелов (куда стрелял)
            "current_player": self.players[self.current_player_index],  # кто ходит
            "you": self.players[viewer_index],  # текущий игрок
            "opponent": self.players[enemy_index],  # соперник
            "game_over": self.game_over,  # завершена ли игра
            "winner": self.winner,  # победитель
            "board_size": self.BOARD_SIZE,  # размер поля
            "letters": self.LETTERS,  # буквы для координат
            "your_ships_left": sum(0 if s["sunk"] else 1 for s in self.ships[viewer_index]),  # сколько своих кораблей осталось
            "enemy_ships_left": sum(0 if s["sunk"] else 1 for s in self.ships[enemy_index]),  # сколько кораблей противника осталось
        }

    def get_state_for_player(self, player_id: str) -> Dict[str, Any]:
        """получает состояние игры для конкретного игрока по его id"""
        idx = 0 if self.players[0]["id"] == player_id else 1  # определяем индекс игрока
        return self._public_view(idx)  # возвращаем представление

    def _coord_to_text(self, row: int, col: int) -> str:
        """преобразует координаты (строка, колонка) в текстовый вид (например, А5)"""
        return f"{self.LETTERS[col]}{row + 1}"

    def _get_ship_at(self, player_index: int, row: int, col: int) -> Optional[Dict[str, Any]]:
        """находит корабль по координатам клетки"""
        for ship in self.ships[player_index]:  # проходим по всем кораблям игрока
            if (row, col) in ship["cells"]:  # если координаты принадлежат кораблю
                return ship
        return None  # корабль не найден

    def shoot(self, player_id: str, coord: str) -> Dict[str, Any]:
        """выполняет выстрел по координатам"""
        if self.game_over:  # если игра уже завершена
            return {"success": False, "message": "Игра уже завершена"}
        shooter_index = 0 if self.players[0]["id"] == player_id else 1  # индекс стреляющего
        if player_id != self.players[self.current_player_index]["id"]:  # проверка очереди хода
            return {"success": False, "message": "Сейчас не ваш ход"}
        row, col = self.parse_coord(coord)  # парсим координаты
        if row is None or col is None:
            return {"success": False, "message": "Координаты в формате А5, Б3 и т.п."}
        if self.shots[shooter_index][row][col] != " ":  # проверяем, не стреляли ли уже сюда
            return {"success": False, "message": "Вы уже стреляли в эту клетку"}

        # индекс соперника нужен для проверки попадания
        enemy_index = 1 - shooter_index  # индекс противника
        enemy_cell = self.boards[enemy_index][row][col]  # что находится в клетке у противника
        result = "miss"  # результат по умолчанию - промах
        message = f"Промах по {self._coord_to_text(row, col)}"  # сообщение по умолчанию
        sunk_ship_size = None  # размер потопленного корабля (если есть)
        
        if enemy_cell == "S":  # если попали в корабль
            self.boards[enemy_index][row][col] = "X"  # отмечаем попадание на поле противника
            self.shots[shooter_index][row][col] = "X"  # отмечаем попадание на поле выстрелов
            ship = self._get_ship_at(enemy_index, row, col)  # находим корабль
            if ship is not None:
                ship["hits"].add((row, col))  # добавляем попадание
                if len(ship["hits"]) == len(ship["cells"]):  # если все клетки корабля подбиты
                    ship["sunk"] = True  # корабль потоплен
                    result = "sunk"  # результат - потопил
                    sunk_ship_size = ship["size"]  # запоминаем размер потопленного
                    message = f"Корабль уничтожен: {ship['size']}-палубный"
                else:
                    result = "hit"  # результат - попадание
                    message = f"Попадание по {self._coord_to_text(row, col)}! Ваш ход продолжается"
            
            # проверяем, потоплены ли все корабли противника
            if all(ship["sunk"] for ship in self.ships[enemy_index]):
                self.game_over = True  # игра завершена
                self.winner = self.players[shooter_index]  # победитель - стреляющий
                message = f"Все корабли противника уничтожены! Победил {self.winner['name']}"
        else:  # промах
            self.boards[enemy_index][row][col] = "M"  # отмечаем промах на поле противника
            self.shots[shooter_index][row][col] = "M"  # отмечаем промах на поле выстрелов
            self.current_player_index = enemy_index  # ход переходит противнику

        return {
            "success": True,
            "message": message,
            "result": result,  # miss / hit / sunk
            "sunk_ship_size": sunk_ship_size,  # размер потопленного корабля
            "game_over": self.game_over,  # завершена ли игра
            "winner": self.winner,  # победитель
            "state": self.get_state_for_player(player_id),  # текущее состояние игры
        }

    @classmethod
    def parse_coord(cls, raw: str) -> tuple[Optional[int], Optional[int]]:
        """преобразует текстовые координаты (например, 'А5') в индексы строки и колонки"""
        if not raw:
            return None, None
        cleaned = raw.strip().upper().replace(" ", "")  # удаляем пробелы и приводим к верхнему регистру
        if len(cleaned) < 2:  # минимум буква + цифра
            return None, None
        letter = cleaned[0]  # первая буква - колонка
        if letter == "A":  # если пользователь ввёл латинскую A
            letter = "А"   # заменяем на русскую А
        if letter not in cls.LETTERS:  # проверяем, что буква допустимая
            return None, None
        number = cleaned[1:]  # остальная часть - номер строки
        if not number.isdigit():  # проверяем, что это цифры
            return None, None
        row = int(number) - 1  # преобразуем в индекс (строки нумеруются с 0)
        col = cls.LETTERS.index(letter)  # получаем индекс колонки
        if not (0 <= row < cls.BOARD_SIZE):  # проверяем, что строка в пределах поля
            return None, None
        return row, col  # возвращаем координаты
