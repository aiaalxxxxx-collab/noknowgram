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

# Простая база данных в памяти
users_db = {}
messages_db = {'general': []}
online_users = {}
groups = {
    'general': {'name': 'Общий чат', 'members': []},
    'friends': {'name': 'Друзья', 'members': []},
    'work': {'name': 'Работа', 'members': []}
}

# Главная страница
@app.route('/')
def serve_index():
    return send_file('index.html')

# Статические файлы
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

# Загрузка файлов
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    # Простая проверка типа файла
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
    for username, data in online_users.items():
        if data.get('sid') == request.sid:
            del online_users[username]
            emit('user_left', {'username': username}, broadcast=True)
            break

@socketio.on('user_join')
def handle_user_join(data):
    username = data['username']
    online_users[username] = {'sid': request.sid}
    emit('user_joined', {'username': username}, broadcast=True)
    emit('online_users', {'users': list(online_users.keys())}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    room = data.get('room', 'general')
    
    if room not in messages_db:
        messages_db[room] = []
    
    message = {
        'id': len(messages_db[room]) + 1,
        'username': data['username'],
        'text': data.get('text', ''),
        'file': data.get('file'),
        'timestamp': datetime.now().isoformat(),
        'type': data.get('type', 'text'),
        'room': room
    }
    
    messages_db[room].append(message)
    emit('new_message', message, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {
        'username': data['username'],
        'is_typing': data['is_typing']
    }, broadcast=True)
# WebRTC signaling - ИСПРАВЛЕННЫЕ ЗВОНКИ
@socketio.on('start_call')
def handle_start_call(data):
    # Отправляем только конкретному пользователю
    target_user = online_users.get(data.get('target'))
    if target_user:
        emit('incoming_call', {
            'caller': data['username'],
            'type': data.get('type', 'voice'),
            'call_id': data.get('call_id')
        }, room=target_user['sid'])

@socketio.on('accept_call')
def handle_accept_call(data):
    # Уведомляем звонящего, что звонок принят
    caller_user = online_users.get(data['caller'])
    if caller_user:
        emit('call_accepted', {
            'accepted_by': data['username'],
            'call_id': data['call_id']
        }, room=caller_user['sid'])

@socketio.on('reject_call')
def handle_reject_call(data):
    # Уведомляем звонящего, что звонок отклонен
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

# WebRTC signaling для передачи медиа-данных
@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    target_user = online_users.get(data['target_user'])
    if target_user:
        emit('webrtc_offer', {
            'offer': data['offer'],
            'caller': data['caller'],
            'call_id': data['call_id']
        }, room=target_user['sid'])

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    target_user = online_users.get(data['target_user'])
    if target_user:
        emit('webrtc_answer', {
            'answer': data['answer'],
            'call_id': data['call_id']
        }, room=target_user['sid'])

@socketio.on('webrtc_ice_candidate')
def handle_webrtc_ice_candidate(data):
    target_user = online_users.get(data['target_user'])
    if target_user:
        emit('webrtc_ice_candidate', {
            'candidate': data['candidate'],
            'call_id': data['call_id']
        }, room=target_user['sid'])

@socketio.on('end_call')
def handle_end_call(data):
    emit('call_ended', {
        'ended_by': data['username']
    }, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print("🚀 NoknowGram Simple Server запущен!")
    print(f"🌐 Порт: {port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
