"""
Модуль игры "Морской бой" для двух игроков.
"""

import random
from typing import Any, Dict, List, Optional


class BattleshipGame:
    BOARD_SIZE = 10
    FLEET = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
    LETTERS = "АБВГДЕЖЗИК"

    def __init__(self, room_id: str, players: List[Dict[str, str]]) -> None:
        self.room_id = room_id
        self.players = players[:2]
        self.current_player_index = random.randint(0, 1)
        self.game_over = False
        self.winner: Optional[Dict[str, Any]] = None

        self.boards = [self._create_empty_board(), self._create_empty_board()]
        self.shots = [self._create_empty_board(), self._create_empty_board()]
        self.ships: List[List[Dict[str, Any]]] = [[], []]
        self._place_random_fleet(0)
        self._place_random_fleet(1)

    def _create_empty_board(self) -> List[List[str]]:
        return [[" " for _ in range(self.BOARD_SIZE)] for _ in range(self.BOARD_SIZE)]

    def _place_random_fleet(self, player_index: int) -> None:
        board = self.boards[player_index]
        ships: List[Dict[str, Any]] = []
        for length in self.FLEET:
            placed = False
            for _ in range(300):
                horizontal = random.choice([True, False])
                if horizontal:
                    row = random.randint(0, self.BOARD_SIZE - 1)
                    col = random.randint(0, self.BOARD_SIZE - length)
                    cells = [(row, col + i) for i in range(length)]
                else:
                    row = random.randint(0, self.BOARD_SIZE - length)
                    col = random.randint(0, self.BOARD_SIZE - 1)
                    cells = [(row + i, col) for i in range(length)]
                if self._can_place_ship(board, cells):
                    for r, c in cells:
                        board[r][c] = "S"
                    ships.append({"cells": cells, "hits": set(), "size": length, "sunk": False})
                    placed = True
                    break
            if not placed:
                raise RuntimeError("Не удалось автоматически расставить все корабли")
        self.ships[player_index] = ships

    def _can_place_ship(self, board: List[List[str]], cells: List[tuple[int, int]]) -> bool:
        for r, c in cells:
            if board[r][c] != " ":
                return False
            for rr in range(max(0, r - 1), min(self.BOARD_SIZE, r + 2)):
                for cc in range(max(0, c - 1), min(self.BOARD_SIZE, c + 2)):
                    if board[rr][cc] == "S":
                        return False
        return True

    def _public_view(self, viewer_index: int) -> Dict[str, Any]:
        enemy_index = 1 - viewer_index
        return {
            "your_board": self.boards[viewer_index],
            "shots_board": self.shots[viewer_index],
            "current_player": self.players[self.current_player_index],
            "you": self.players[viewer_index],
            "opponent": self.players[enemy_index],
            "game_over": self.game_over,
            "winner": self.winner,
            "board_size": self.BOARD_SIZE,
            "letters": self.LETTERS,
            "your_ships_left": sum(0 if s["sunk"] else 1 for s in self.ships[viewer_index]),
            "enemy_ships_left": sum(0 if s["sunk"] else 1 for s in self.ships[enemy_index]),
        }

    def get_state_for_player(self, player_id: str) -> Dict[str, Any]:
        idx = 0 if self.players[0]["id"] == player_id else 1
        return self._public_view(idx)

    def _coord_to_text(self, row: int, col: int) -> str:
        return f"{self.LETTERS[col]}{row + 1}"

    def _get_ship_at(self, player_index: int, row: int, col: int) -> Optional[Dict[str, Any]]:
        for ship in self.ships[player_index]:
            if (row, col) in ship["cells"]:
                return ship
        return None

    def shoot(self, player_id: str, coord: str) -> Dict[str, Any]:
        if self.game_over:
            return {"success": False, "message": "Игра уже завершена"}
        shooter_index = 0 if self.players[0]["id"] == player_id else 1
        if player_id != self.players[self.current_player_index]["id"]:
            return {"success": False, "message": "Сейчас не ваш ход"}
        row, col = self.parse_coord(coord)
        if row is None or col is None:
            return {"success": False, "message": "Координаты в формате А5, Б3 и т.п."}
        if self.shots[shooter_index][row][col] != " ":
            return {"success": False, "message": "Вы уже стреляли в эту клетку"}

        enemy_index = 1 - shooter_index
        enemy_cell = self.boards[enemy_index][row][col]
        result = "miss"
        message = f"Промах по {self._coord_to_text(row, col)}"
        sunk_ship_size = None
        if enemy_cell == "S":
            self.boards[enemy_index][row][col] = "X"
            self.shots[shooter_index][row][col] = "X"
            ship = self._get_ship_at(enemy_index, row, col)
            if ship is not None:
                ship["hits"].add((row, col))
                if len(ship["hits"]) == len(ship["cells"]):
                    ship["sunk"] = True
                    result = "sunk"
                    sunk_ship_size = ship["size"]
                    message = f"Корабль уничтожен: {ship['size']}-палубный"
                else:
                    result = "hit"
                    message = f"Попадание по {self._coord_to_text(row, col)}! Ваш ход продолжается"
            if all(ship["sunk"] for ship in self.ships[enemy_index]):
                self.game_over = True
                self.winner = self.players[shooter_index]
                message = f"Все корабли противника уничтожены! Победил {self.winner['name']}"
        else:
            self.boards[enemy_index][row][col] = "M"
            self.shots[shooter_index][row][col] = "M"
            self.current_player_index = enemy_index

        return {
            "success": True,
            "message": message,
            "result": result,
            "sunk_ship_size": sunk_ship_size,
            "game_over": self.game_over,
            "winner": self.winner,
            "state": self.get_state_for_player(player_id),
        }

    @classmethod
    def parse_coord(cls, raw: str) -> tuple[Optional[int], Optional[int]]:
        if not raw:
            return None, None
        cleaned = raw.strip().upper().replace(" ", "")
        if len(cleaned) < 2:
            return None, None
        letter = cleaned[0]
        if letter == "A":
            letter = "А"
        if letter not in cls.LETTERS:
            return None, None
        number = cleaned[1:]
        if not number.isdigit():
            return None, None
        row = int(number) - 1
        col = cls.LETTERS.index(letter)
        if not (0 <= row < cls.BOARD_SIZE):
            return None, None
        return row, col
