from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'roomiverse-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Хранилище данных (в памяти)
rooms = {}        # {код_комнаты: {players: [], scores: {}}}
players = {}      # {sid: {name: '', room: ''}}

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/lobby')
def lobby():
    return render_template('lobby.html')

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
        'created_by': player_name
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

if __name__ == '__main__':
    print('Сервер ROOMIVERSE запущен на http://localhost:5000')
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
