"""
модуль игры "Крестики-нолики" 
Поле 9x9, победа - 5 символов в ряд
"""

import random
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

class TicTacToeGame:
    """
    Класс для игры в крестики-нолики на поле 9x9
    """
    
    def __init__(self, room_id: str, players: List[Dict[str, str]], board_size: int = 9):
        """
        Инициализация игры
        """
        self.room_id = room_id
        self.players = players
        self.board_size = board_size
        self.win_condition = 5  # Для победы нужно 5 в ряд
        
        # Игровое поле 9x9, заполнено пробелами
        self.board = [[' ' for _ in range(board_size)] for _ in range(board_size)]
        
        # Случайный выбор первого игрока
        self.current_player_index = random.randint(0, 1)
        
        # Символы игроков
        self.player_symbols = ['X', 'O']
        
        # Статус игры
        self.game_over = False
        self.winner: Optional[Dict[str, Any]] = None
        self.is_draw = False
        
        # История ходов
        self.move_history = []
    
    def get_current_player(self) -> Dict[str, Any]:
        """Возвращает информацию о текущем игроке"""
        return {
            'id': self.players[self.current_player_index]['id'],
            'name': self.players[self.current_player_index]['name'],
            'symbol': self.player_symbols[self.current_player_index]
        }
    
    def get_board_state(self) -> Dict[str, Any]:
        """
        Возвращает полное состояние игры для отправки клиентам
        """
        xo_players = [
            {
                "id": self.players[i]["id"],
                "name": self.players[i]["name"],
                "symbol": self.player_symbols[i],
            }
            for i in range(min(2, len(self.players)))
        ]
        return {
            "board": self.board,
            "board_size": self.board_size,
            "current_player": self.get_current_player(),
            "xo_players": xo_players,
            "game_over": self.game_over,
            "winner": self.winner,
            "is_draw": self.is_draw,
            "move_count": len(self.move_history),
        }
    
    def make_move(self, player_id: str, row: int, col: int) -> Dict[str, Any]:
        """
        Обрабатывает ход игрока
        """
        # Проверка 1: Игра не должна быть закончена
        if self.game_over:
            return {
                'success': False,
                'message': 'Игра уже закончена',
                'game_state': self.get_board_state()
            }
        
        # Проверка 2: Проверка очереди хода
        if player_id != self.players[self.current_player_index]['id']:
            return {
                'success': False,
                'message': 'Сейчас не ваш ход',
                'game_state': self.get_board_state()
            }
        
        # Проверка 3: Валидация координат
        if not (0 <= row < self.board_size and 0 <= col < self.board_size):
            return {
                'success': False,
                'message': f'Неверные координаты. Допустимы значения от 0 до {self.board_size-1}',
                'game_state': self.get_board_state()
            }
        
        # Проверка 4: Клетка должна быть свободна
        if self.board[row][col] != ' ':
            return {
                'success': False,
                'message': 'Эта клетка уже занята',
                'game_state': self.get_board_state()
            }
        
        # ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - совершаем ход
        symbol = self.player_symbols[self.current_player_index]
        self.board[row][col] = symbol
        
        # Записываем в историю
        self.move_history.append({
            'player': self.players[self.current_player_index]['name'],
            'symbol': symbol,
            'row': row,
            'col': col
        })
        
        # Проверка победы
        if self._check_win(row, col, symbol):
            self.game_over = True
            self.winner = {
                'id': self.players[self.current_player_index]['id'],
                'name': self.players[self.current_player_index]['name'],
                'symbol': symbol
            }
        # Проверка ничьей
        elif self._is_board_full():
            self.game_over = True
            self.is_draw = True
        # Переключаем игрока
        else:
            self.current_player_index = 1 - self.current_player_index
        
        return {
            'success': True,
            'message': 'Ход выполнен успешно',
            'game_state': self.get_board_state(),
            'move': {
                'row': row,
                'col': col,
                'symbol': symbol
            }
        }
    
    def _check_win(self, row: int, col: int, symbol: str) -> bool:
        """
        Проверяет победу после хода
        """
        directions = [
            (0, 1),   # горизонталь (вправо)
            (1, 0),   # вертикаль (вниз)
            (1, 1),   # диагональ вниз-вправо
            (1, -1)   # диагональ вниз-влево
        ]
        
        for dr, dc in directions:
            count = 1  # Начинаем с текущей клетки
            
            # Положительное направление
            r, c = row + dr, col + dc
            while (0 <= r < self.board_size and 
                   0 <= c < self.board_size and 
                   self.board[r][c] == symbol):
                count += 1
                r += dr
                c += dc
            
            # Отрицательное направление
            r, c = row - dr, col - dc
            while (0 <= r < self.board_size and 
                   0 <= c < self.board_size and 
                   self.board[r][c] == symbol):
                count += 1
                r -= dr
                c -= dc
            
            # Если набрали нужное количество (5) - победа
            if count >= self.win_condition:
                return True
        
        return False
    
    def _is_board_full(self) -> bool:
        """Проверяет, заполнено ли поле"""
        for row in self.board:
            if ' ' in row:
                return False
        return True
    
    def get_game_summary(self) -> Dict[str, Any]:
        """
        Возвращает сводку по игре для сохранения в БД
        """
        return {
            'room_id': self.room_id,
            'game_type': f'tictactoe_{self.board_size}x{self.board_size}',
            'players': self.players,
            'winner': self.winner,
            'is_draw': self.is_draw,
            'move_count': len(self.move_history),
            'move_history': self.move_history
        }
    
    def get_rating_update(self) -> List[Dict[str, Any]]:
        """
        Возвращает обновления рейтинга для БД
        Согласно ТЗ: +10 победителю, -5 проигравшему
        """
        updates = []
        
        if self.winner:
            # Победитель получает +10
            updates.append({
                'player_id': self.winner['id'],
                'player_name': self.winner['name'],
                'rating_change': 10,
                'reason': 'win'
            })
            
            # Проигравший получает -5
            loser = next(p for p in self.players if p['id'] != self.winner['id'])
            updates.append({
                'player_id': loser['id'],
                'player_name': loser['name'],
                'rating_change': -5,
                'reason': 'loss'
            })
        elif self.is_draw:
            # При ничьей очки не меняются
            for player in self.players:
                updates.append({
                    'player_id': player['id'],
                    'player_name': player['name'],
                    'rating_change': 0,
                    'reason': 'draw'
                })
        
        return updates
