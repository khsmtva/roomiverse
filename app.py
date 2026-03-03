from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room
import random
import string
from games.XO import TicTacToeGame  # ИЗМЕНЕНО: вместо tictactoe.py теперь XO.py

app = Flask(__name__)
app.config['SECRET_KEY'] = 'roomiverse-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Хранилище данных
rooms = {}        # {код_комнаты: {players: [], scores: {}, game: None, game_type: ''}}
players = {}      # {sid: {name: '', room: ''}}

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/lobby')
def lobby():
    return render_template('lobby.html')

@app.route('/game/<room_code>')
def game_page(room_code):
    """Страница игры"""
    return render_template('XO.html', room_code=room_code)  # ИЗМЕНЕНО: вместо game.html теперь XO.html

# ========== API ДЛЯ КОМНАТ ==========

@app.route('/api/create_room', methods=['POST'])
def create_room():
    data = request.json
    player_name = data.get('name', 'Игрок')
    
    room_code = generate_room_code()
    while room_code in rooms:
        room_code = generate_room_code()
    
    rooms[room_code] = {
        'players': [],
        'scores': {},
        'created_by': player_name,
        'game': None,
        'game_type': None
    }
    
    return jsonify({
        'success': True,
        'room_code': room_code,
        'message': 'Комната создана'
    })

@app.route('/api/join_room', methods=['POST'])
def join_room_api():
    data = request.json
    room_code = data.get('room_code', '').upper()
    player_name = data.get('name', '')
    
    if room_code not in rooms:
        return jsonify({
            'success': False,
            'message': 'Комната не найдена'
        })
    
    if len(rooms[room_code]['players']) >= 6:
        return jsonify({
            'success': False,
            'message': 'В комнате нет свободных мест'
        })
    
    return jsonify({
        'success': True,
        'room_code': room_code,
        'message': 'Подключение выполнено'
    })

# ========== API ДЛЯ ИГР ==========

@app.route('/api/start_game/<room_code>', methods=['POST'])
def start_game(room_code):
    """Начать игру в комнате"""
    data = request.json
    game_type = data.get('game_type', 'tictactoe')
    
    if room_code not in rooms:
        return jsonify({'success': False, 'message': 'Комната не найдена'})
    
    room = rooms[room_code]
    
    # Проверяем количество игроков
    if len(room['players']) < 2:
        return jsonify({'success': False, 'message': 'Нужно минимум 2 игрока'})
    
    # Берем первых двух игроков
    player1 = room['players'][0]['name']
    player2 = room['players'][1]['name']
    
    players_list = [
        {'id': 'p1', 'name': player1},
        {'id': 'p2', 'name': player2}
    ]
    
    # Создаем игру
    if game_type == 'tic_tac_toe':
        game = TicTacToeGame(room_code, players_list, board_size=9)
        room['game'] = game
        room['game_type'] = 'tictactoe'
        
        # Оповещаем всех в комнате
        socketio.emit('game_started', {
            'game_type': 'tic_tac_toe',
            'room_code': room_code
        }, room=room_code)
        
        return jsonify({
            'success': True,
            'game_type': 'tictactoe',
            'game_state': game.get_board_state()
        })
    else:
        return jsonify({'success': False, 'message': 'Неизвестный тип игры'})

@app.route('/api/game_state/<room_code>')
def game_state(room_code):
    """Получить состояние игры"""
    if room_code not in rooms:
        return jsonify({'error': 'Игра не найдена'}), 404
    
    room = rooms[room_code]
    if not room['game']:
        return jsonify({'error': 'Игра не начата'}), 404
    
    return jsonify(room['game'].get_board_state())

@app.route('/api/make_move', methods=['POST'])
def make_move():
    """Сделать ход"""
    data = request.json
    room_code = data['room_code']
    
    if room_code not in rooms:
        return jsonify({'success': False, 'message': 'Игра не найдена'})
    
    room = rooms[room_code]
    if not room['game']:
        return jsonify({'success': False, 'message': 'Игра не начата'})
    
    # Делаем ход
    result = room['game'].make_move(
        data['player_id'],
        data['row'],
        data['col']
    )
    
    # Если игра закончилась, обновляем счет
    if result['success'] and result['game_state']['game_over']:
        winner = result['game_state']['winner']
        if winner:
            # +10 победителю
            rooms[room_code]['scores'][winner['name']] = \
                rooms[room_code]['scores'].get(winner['name'], 0) + 10
            # -5 проигравшему
            if winner['id'] == 'p1':
                loser_name = room['players'][1]['name']
            else:
                loser_name = room['players'][0]['name']
            rooms[room_code]['scores'][loser_name] = \
                rooms[room_code]['scores'].get(loser_name, 0) - 5
    
    return jsonify(result)

# ========== СОКЕТЫ ==========

@socketio.on('connect')
def handle_connect():
    print(f'Клиент подключился: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Клиент отключился: {request.sid}')
    
    if request.sid in players:
        player = players[request.sid]
        room_code = player['room']
        
        if room_code in rooms:
            rooms[room_code]['players'] = [
                p for p in rooms[room_code]['players'] 
                if p['sid'] != request.sid
            ]
            
            emit('players_update', {
                'players': [p['name'] for p in rooms[room_code]['players']]
            }, room=room_code)
            
            if len(rooms[room_code]['players']) == 0:
                del rooms[room_code]
                print(f'Комната {room_code} удалена')
        
        del players[request.sid]

@socketio.on('join_room')
def handle_join_room(data):
    room_code = data['room_code']
    player_name = data['name']
    
    if room_code not in rooms:
        emit('error', {'message': 'Комната не найдена'})
        return
    
    join_room(room_code)
    
    players[request.sid] = {
        'name': player_name,
        'room': room_code
    }
    
    rooms[room_code]['players'].append({
        'sid': request.sid,
        'name': player_name
    })
    
    if player_name not in rooms[room_code]['scores']:
        rooms[room_code]['scores'][player_name] = 0
    
    emit('players_update', {
        'players': [p['name'] for p in rooms[room_code]['players']]
    }, room=room_code)
    
    emit('joined_room', {
        'room_code': room_code,
        'players': [p['name'] for p in rooms[room_code]['players']]
    })

@socketio.on('send_message')
def handle_send_message(data):
    room_code = data['room_code']
    message = data['message']
    
    if request.sid in players:
        player_name = players[request.sid]['name']
        
        emit('new_message', {
            'sender': player_name,
            'message': message,
            'time': 'сейчас'
        }, room=room_code)

 ========== ЗАПУСК ==========

if __name__ == '__main__':
    print('\n' + '='*60)
    print('🚀 ROOMIVERSE - СЕРВЕР ЗАПУЩЕН')
    print('='*60)
    print('📱 Главная страница: http://localhost:5000')
    print('🎮 Крестики-нолики 9x9 готовы')
    print('='*60 + '\n')
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
