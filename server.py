import os
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
import hashlib
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'noknowgram-simple-secret'
app.config['UPLOAD_FOLDER'] = 'uploads'

socketio = SocketIO(app, cors_allowed_origins="*")

# Создаем папки
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# База данных
users_db = {}
messages_db = {
    'general': [],
    'friends': [], 
    'work': []
}
private_messages = {}
online_users = {}

@app.route('/')
def serve_index():
    return send_file('index.html')

@app.route('/chat.html')
def serve_chat():
    return send_file('chat.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# API для регистрации/входа
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    
    if username in users_db:
        return jsonify({'success': False, 'message': 'Пользователь уже существует'})
    
    users_db[username] = {
        'password_hash': hashlib.sha256(password.encode()).hexdigest(),
        'created_at': datetime.now().isoformat()
    }
    
    return jsonify({'success': True, 'message': 'Пользователь создан'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    
    user = users_db.get(username)
    if user and user['password_hash'] == hashlib.sha256(password.encode()).hexdigest():
        return jsonify({'success': True, 'message': 'Успешный вход'})
    
    return jsonify({'success': False, 'message': 'Неверный логин или пароль'})

# API для получения сообщений
@app.route('/api/messages/<room>')
def get_messages(room):
    if room.startswith('private_'):
        messages = private_messages.get(room, [])
    else:
        messages = messages_db.get(room, [])
    return jsonify({'messages': messages})

# Загрузка файлов
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'txt', 'pdf'}
    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    
    if file_ext not in allowed_extensions:
        return jsonify({'success': False, 'message': 'Недопустимый тип файла'})
    
    filename = f"{uuid.uuid4().hex}.{file_ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    return jsonify({
        'success': True,
        'filename': filename,
        'original_name': file.filename,
        'url': f'/uploads/{filename}'
    })

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# WebSocket события
@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    for username, data in list(online_users.items()):
        if data.get('sid') == request.sid:
            del online_users[username]
            emit('user_left', {'username': username}, broadcast=True)
            # ОБНОВЛЯЕМ список онлайн у всех пользователей
            emit('online_users', {'users': list(online_users.keys())}, broadcast=True)
            break

@socketio.on('user_join')
def handle_user_join(data):
    username = data['username']
    online_users[username] = {'sid': request.sid}
    
    # ОТПРАВЛЯЕМ новому пользователю текущий список онлайн
    emit('online_users', {'users': list(online_users.keys())}, room=request.sid)
    
    # Уведомляем всех о новом пользователе
    emit('user_joined', {'username': username}, broadcast=True)
    
    # ОБНОВЛЯЕМ список онлайн у всех пользователей
    emit('online_users', {'users': list(online_users.keys())}, broadcast=True)

@socketio.on('join_room')
def handle_join_room(data):
    room = data.get('room', 'general')
    join_room(room)

@socketio.on('send_message')
def handle_message(data):
    room = data.get('room', 'general')
    
    message = {
        'id': str(uuid.uuid4()),
        'username': data['username'],
        'text': data.get('text', ''),
        'file': data.get('file'),
        'timestamp': datetime.now().isoformat(),
        'type': data.get('type', 'text'),
        'room': room
    }
    
    # Сохраняем в нужную комнату
    if room.startswith('private_'):
        if room not in private_messages:
            private_messages[room] = []
        private_messages[room].append(message)
    else:
        if room not in messages_db:
            messages_db[room] = []
        messages_db[room].append(message)
    
    # Отправляем в комнату
    emit('new_message', message, room=room)

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {
        'username': data['username'],
        'is_typing': data['is_typing'],
        'room': data.get('room', 'general')
    }, room=data.get('room', 'general'))

# ЗВОНКИ
@socketio.on('start_call')
def handle_start_call(data):
    target_user = online_users.get(data.get('target'))
    if target_user:
        emit('incoming_call', {
            'caller': data['username'],
            'type': data.get('type', 'voice'),
            'call_id': data.get('call_id')
        }, room=target_user['sid'])

@socketio.on('accept_call')
def handle_accept_call(data):
    caller_user = online_users.get(data['caller'])
    if caller_user:
        emit('call_accepted', {
            'accepted_by': data['username'],
            'call_id': data['call_id']
        }, room=caller_user['sid'])

@socketio.on('reject_call')
def handle_reject_call(data):
    caller_user = online_users.get(data['caller'])
    if caller_user:
        emit('call_rejected', {
            'rejected_by': data['username'],
            'call_id': data['call_id']
        }, room=caller_user['sid'])

@socketio.on('end_call')
def handle_end_call(data):
    emit('call_ended', {
        'ended_by': data['username'],
        'call_id': data.get('call_id')
    }, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print("🚀 NoknowGram Messenger запущен!")
    print(f"🌐 Порт: {port}")
    print("💬 Личные сообщения: ВКЛ")
    print("🔊 Звук звонков: ВКЛ")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
