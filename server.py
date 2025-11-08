# ВСТАВЬТЕ ВЕСЬ ЭТОТ КОД В server.py ВМЕСТО СТАРОГО
import os
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
import hashlib
import uuid
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'noknowgram-simple-secret'
app.config['UPLOAD_FOLDER'] = 'uploads'

socketio = SocketIO(app, cors_allowed_origins="*")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# База данных
users_db = {}
messages_db = {}
online_users = {}
groups_db = {}
user_groups = {}

# Глобальные чаты
DEFAULT_ROOMS = {
    'general': '🌍 Главный чат',
    'random': '🎮 Развлечения', 
    'help': '❓ Помощь'
}

# WebRTC пары (call_id -> данные)
webrtc_sessions = {}

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
    messages = messages_db.get(room, [])
    return jsonify({'messages': messages})

# API для групп
@app.route('/api/groups/create', methods=['POST'])
def create_group():
    data = request.get_json()
    group_name = data.get('name', '').strip()
    creator = data.get('creator', '')
    members = data.get('members', [])
    
    if not group_name or not creator:
        return jsonify({'success': False, 'message': 'Неверные данные'})
    
    group_id = f"group_{uuid.uuid4().hex[:8]}"
    groups_db[group_id] = {
        'id': group_id,
        'name': group_name,
        'creator': creator,
        'members': list(set([creator] + members)),
        'created_at': datetime.now().isoformat()
    }
    
    # Создаем комнату для группы
    messages_db[group_id] = []
    
    # Добавляем группу пользователям
    for member in groups_db[group_id]['members']:
        if member not in user_groups:
            user_groups[member] = []
        user_groups[member].append(group_id)
    
    return jsonify({'success': True, 'group': groups_db[group_id]})

@app.route('/api/groups/<username>')
def get_user_groups(username):
    user_groups_list = user_groups.get(username, [])
    groups_data = [groups_db[group_id] for group_id in user_groups_list if group_id in groups_db]
    return jsonify({'groups': groups_data})

# Загрузка файлов
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    # Определяем тип файла
    original_name = file.filename
    file_ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    
    file_types = {
        'images': {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'},
        'videos': {'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'},
        'audio': {'mp3', 'wav', 'ogg', 'm4a', 'flac'},
        'documents': {'pdf', 'doc', 'docx', 'txt', 'rtf', 'xls', 'xlsx', 'ppt', 'pptx'},
        'archives': {'zip', 'rar', '7z', 'tar', 'gz'}
    }
    
    file_type = 'other'
    for type_name, extensions in file_types.items():
        if file_ext in extensions:
            file_type = type_name
            break
    
    filename = f"{uuid.uuid4().hex}.{file_ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    # Получаем размер файла
    file_size = os.path.getsize(filepath)
    
    return jsonify({
        'success': True,
        'filename': filename,
        'original_name': original_name,
        'url': f'/uploads/{filename}',
        'type': file_type,
        'size': file_size,
        'extension': file_ext
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
            emit('online_users', {'users': list(online_users.keys())}, broadcast=True)
            break

@socketio.on('user_join')
def handle_user_join(data):
    username = data['username']
    online_users[username] = {'sid': request.sid}
    
    # Отправляем пользователю список онлайн и его группы
    emit('online_users', {'users': list(online_users.keys())}, room=request.sid)
    emit('user_joined', {'username': username}, broadcast=True)
    emit('online_users', {'users': list(online_users.keys())}, broadcast=True)
    
    # Отправляем группы пользователя
    user_groups_list = user_groups.get(username, [])
    groups_data = [groups_db[group_id] for group_id in user_groups_list if group_id in groups_db]
    emit('user_groups', {'groups': groups_data}, room=request.sid)

@socketio.on('join_room')
def handle_join_room(data):
    room = data.get('room', 'general')
    join_room(room)

@socketio.on('send_message')
def handle_message(data):
    room = data.get('room', 'general')
    
    if room not in messages_db:
        messages_db[room] = []
    
    message = {
        'id': str(uuid.uuid4()),
        'username': data['username'],
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_info': data.get('file_info'),
        'timestamp': datetime.now().isoformat(),
        'type': data.get('type', 'text'),
        'room': room
    }
    
    messages_db[room].append(message)
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
    target = data.get('target')
    call_type = data.get('type', 'voice')
    call_id = data.get('call_id')
    
    if target.startswith('group_'):
        # Групповой звонок
        group = groups_db.get(target)
        if group:
            for member in group['members']:
                if member != data['username'] and member in online_users:
                    emit('incoming_call', {
                        'caller': data['username'],
                        'type': call_type,
                        'call_id': call_id,
                        'is_group': True,
                        'group_name': group['name']
                    }, room=online_users[member]['sid'])
    else:
        # Личный звонок
        target_user = online_users.get(target)
        if target_user:
            emit('incoming_call', {
                'caller': data['username'],
                'type': call_type,
                'call_id': call_id,
                'is_group': False
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

# WebRTC signaling - ПОЛНАЯ РЕАЛИЗАЦИЯ
@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    call_id = data.get('call_id')
    target = data.get('target')
    
    # Сохраняем оффер
    if call_id not in webrtc_sessions:
        webrtc_sessions[call_id] = {}
    webrtc_sessions[call_id]['offer'] = data['offer']
    
    if target.startswith('group_'):
        # Групповой звонок
        group = groups_db.get(target)
        if group:
            for member in group['members']:
                if member != data['caller'] and member in online_users:
                    emit('webrtc_offer', {
                        'offer': data['offer'],
                        'caller': data['caller'],
                        'call_id': call_id,
                        'target': target
                    }, room=online_users[member]['sid'])
    else:
        # Личный звонок
        target_user = online_users.get(target)
        if target_user:
            emit('webrtc_offer', {
                'offer': data['offer'],
                'caller': data['caller'],
                'call_id': call_id
            }, room=target_user['sid'])

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    call_id = data.get('call_id')
    
    # Сохраняем ответ
    if call_id in webrtc_sessions:
        webrtc_sessions[call_id]['answer'] = data['answer']
    
    # Пересылаем звонящему
    caller_user = online_users.get(data['caller'])
    if caller_user:
        emit('webrtc_answer', {
            'answer': data['answer'],
            'call_id': call_id
        }, room=caller_user['sid'])

@socketio.on('webrtc_ice_candidate')
def handle_webrtc_ice_candidate(data):
    call_id = data.get('call_id')
    target = data.get('target')
    
    if target.startswith('group_'):
        # Групповой звонок
        group = groups_db.get(target)
        if group:
            for member in group['members']:
                if member != data['caller'] and member in online_users:
                    emit('webrtc_ice_candidate', {
                        'candidate': data['candidate'],
                        'call_id': call_id,
                        'caller': data['caller']
                    }, room=online_users[member]['sid'])
    else:
        # Личный звонок
        target_user = online_users.get(data['target_user'])
        if target_user:
            emit('webrtc_ice_candidate', {
                'candidate': data['candidate'],
                'call_id': call_id,
                'caller': data['caller']
            }, room=target_user['sid'])

@socketio.on('webrtc_end_call')
def handle_webrtc_end_call(data):
    call_id = data.get('call_id')
    # Очищаем сессию
    if call_id in webrtc_sessions:
        del webrtc_sessions[call_id]
    
    emit('webrtc_call_ended', {
        'call_id': call_id
    }, broadcast=True)

if __name__ == '__main__':
    # Инициализируем глобальные чаты
    for room_id, room_name in DEFAULT_ROOMS.items():
        if room_id not in messages_db:
            messages_db[room_id] = []
    
    port = int(os.environ.get('PORT', 10000))
    print("🚀 NoknowGram PRO с видеозвонками запущен!")
    print(f"🌐 Порт: {port}")
    print("📞 WebRTC видеозвонки: ВКЛ")
    print("👥 Групповые звонки: ВКЛ")
    print("🖥️ Демонстрация экрана: ВКЛ")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
