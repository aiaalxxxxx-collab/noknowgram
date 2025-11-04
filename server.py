# server.py
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import os
import hashlib
import uuid
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'noknowgram-mega-secret-2024'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Создаем папки
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# База данных
users_db = {}
messages_db = {
    'general': [],
    'gaming': [],
    'music': []
}
online_users = {}
active_calls = {}
groups = {
    'general': {'name': 'Общий чат', 'members': [], 'type': 'public', 'id': 'general'},
    'gaming': {'name': '🎮 Игровые', 'members': [], 'type': 'public', 'id': 'gaming'},
    'music': {'name': '🎵 Музыка', 'members': [], 'type': 'public', 'id': 'music'}
}

ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'avi', 'mov', 'mkv',
    'mp3', 'wav', 'ogg', 'txt', 'pdf', 'doc', 'docx', 'zip', 'rar'
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, password):
    if username in users_db:
        return False, "Пользователь уже существует"
    
    users_db[username] = {
        'password_hash': hash_password(password),
        'created_at': datetime.now().isoformat(),
        'contacts': [],
        'groups': ['general', 'gaming', 'music']
    }
    return True, "Пользователь создан"

def verify_user(username, password):
    user = users_db.get(username)
    if user and user['password_hash'] == hash_password(password):
        return True, "Успешный вход"
    return False, "Неверный логин или пароль"

# Главная страница
@app.route('/')
def serve_index():
    return send_file('noknowgramstrongvariant.html')

# API endpoints
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    
    success, message = create_user(username, password)
    return jsonify({'success': success, 'message': message})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    
    success, message = verify_user(username, password)
    return jsonify({'success': success, 'message': message})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Файл не выбран'})
    
    if file and allowed_file(file.filename):
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{file_ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'original_name': file.filename,
            'url': f'/uploads/{filename}'
        })
    
    return jsonify({'success': False, 'message': 'Недопустимый тип файла'})

@app.route('/api/messages/<room>')
def get_messages(room):
    return jsonify(messages_db.get(room, []))

@app.route('/api/groups')
def get_groups():
    return jsonify(groups)

@app.route('/api/users')
def get_online_users():
    return jsonify({'users': list(online_users.keys())})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# WebSocket события
@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    username_to_remove = None
    for username, data in online_users.items():
        if data.get('sid') == request.sid:
            username_to_remove = username
            break
    
    if username_to_remove:
        del online_users[username_to_remove]
        emit('user_left', {'username': username_to_remove}, broadcast=True)
        emit('online_users', {'users': list(online_users.keys())}, broadcast=True)
        
        # Завершаем активные звонки пользователя
        for call_id, call_data in active_calls.items():
            if username_to_remove in call_data['users']:
                handle_end_call({'call_id': call_id, 'username': username_to_remove})

@socketio.on('user_join')
def handle_user_join(data):
    username = data['username']
    online_users[username] = {
        'sid': request.sid,
        'joined_at': datetime.now().isoformat()
    }
    
    # Вступаем во все группы пользователя
    user_groups = users_db.get(username, {}).get('groups', ['general'])
    for group in user_groups:
        join_room(group)
        if username not in groups[group]['members']:
            groups[group]['members'].append(username)
    
    emit('user_joined', {'username': username}, broadcast=True)
    emit('online_users', {'users': list(online_users.keys())}, broadcast=True)
    emit('user_groups', {'groups': user_groups}, room=request.sid)

@socketio.on('join_group')
def handle_join_group(data):
    username = data['username']
    group_id = data['group_id']
    
    if group_id not in messages_db:
        messages_db[group_id] = []
    
    if group_id not in groups:
        groups[group_id] = {
            'name': group_id,
            'members': [username],
            'type': 'public',
            'id': group_id
        }
    
    join_room(group_id)
    if username not in groups[group_id]['members']:
        groups[group_id]['members'].append(username)
    
    # Обновляем группы пользователя
    if username in users_db:
        if group_id not in users_db[username]['groups']:
            users_db[username]['groups'].append(group_id)
    
    emit('group_joined', {
        'group_id': group_id,
        'username': username,
        'group_name': groups[group_id]['name']
    }, room=group_id)

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
    emit('new_message', message, room=room, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    room = data.get('room', 'general')
    emit('user_typing', {
        'username': data['username'],
        'is_typing': data['is_typing'],
        'room': room
    }, room=room, broadcast=True)

# Звонки
@socketio.on('start_call')
def handle_start_call(data):
    call_id = str(uuid.uuid4())
    call_type = data.get('type', 'voice')
    caller = data['username']
    target_type = data.get('target_type', 'user')
    target = data.get('target', 'general')
    
    active_calls[call_id] = {
        'users': [caller],
        'type': call_type,
        'caller': caller,
        'target_type': target_type,
        'target': target,
        'status': 'ringing',
        'id': call_id
    }
    
    # Звонок пользователю
    if target_type == 'user' and target in online_users:
        target_sid = online_users[target]['sid']
        emit('incoming_call', {
            'call_id': call_id,
            'caller': caller,
            'type': call_type,
            'target_type': 'user'
        }, room=target_sid)
    
    # Групповой звонок
    elif target_type == 'group' and target in groups:
        group_members = groups[target]['members']
        for member in group_members:
            if member != caller and member in online_users:
                member_sid = online_users[member]['sid']
                emit('incoming_call', {
                    'call_id': call_id,
                    'caller': caller,
                    'type': call_type,
                    'target_type': 'group',
                    'group_name': groups[target]['name']
                }, room=member_sid)
    
    emit('call_started', {
        'call_id': call_id,
        'type': call_type,
        'target_type': target_type,
        'target': target
    }, room=request.sid)

@socketio.on('answer_call')
def handle_answer_call(data):
    call_id = data['call_id']
    username = data['username']
    
    if call_id in active_calls:
        active_calls[call_id]['users'].append(username)
        active_calls[call_id]['status'] = 'active'
        
        # Уведомляем всех участников
        for user in active_calls[call_id]['users']:
            if user in online_users:
                user_sid = online_users[user]['sid']
                emit('call_accepted', {
                    'call_id': call_id,
                    'accepted_by': username,
                    'participants': active_calls[call_id]['users']
                }, room=user_sid)

@socketio.on('reject_call')
def handle_reject_call(data):
    call_id = data['call_id']
    username = data['username']
    
    if call_id in active_calls:
        caller = active_calls[call_id]['caller']
        if caller in online_users:
            caller_sid = online_users[caller]['sid']
            emit('call_rejected', {
                'call_id': call_id,
                'rejected_by': username
            }, room=caller_sid)
        
        if active_calls[call_id]['target_type'] == 'group':
            if len(active_calls[call_id]['users']) == 1:
                del active_calls[call_id]
                emit('call_ended', {
                    'call_id': call_id,
                    'reason': 'Все отклонили звонок'
                }, room=request.sid)

@socketio.on('end_call')
def handle_end_call(data):
    call_id = data['call_id']
    username = data['username']
    
    if call_id in active_calls:
        for user in active_calls[call_id]['users']:
            if user in online_users:
                user_sid = online_users[user]['sid']
                emit('call_ended', {
                    'call_id': call_id,
                    'ended_by': username,
                    'reason': 'Звонок завершен'
                }, room=user_sid)
        
        del active_calls[call_id]

# WebRTC события
@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    target_user = data['target_user']
    if target_user in online_users:
        emit('webrtc_offer', {
            'offer': data['offer'],
            'call_id': data['call_id'],
            'from_user': data['from_user']
        }, room=online_users[target_user]['sid'])

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    target_user = data['target_user']
    if target_user in online_users:
        emit('webrtc_answer', {
            'answer': data['answer'],
            'call_id': data['call_id'],
            'from_user': data['from_user']
        }, room=online_users[target_user]['sid'])

@socketio.on('webrtc_ice_candidate')
def handle_webrtc_ice_candidate(data):
    target_user = data['target_user']
    if target_user in online_users:
        emit('webrtc_ice_candidate', {
            'candidate': data['candidate'],
            'call_id': data['call_id'],
            'from_user': data['from_user']
        }, room=online_users[target_user]['sid'])

@socketio.on('create_group')
def handle_create_group(data):
    group_id = str(uuid.uuid4())[:8]
    group_name = data['group_name']
    creator = data['username']
    
    groups[group_id] = {
        'name': group_name,
        'members': [creator],
        'type': 'private',
        'creator': creator,
        'id': group_id
    }
    
    messages_db[group_id] = []
    
    if creator in users_db:
        users_db[creator]['groups'].append(group_id)
    
    join_room(group_id)
    
    emit('group_created', {
        'group_id': group_id,
        'group_name': group_name,
        'creator': creator
    }, room=request.sid)
    
    # Добавляем в список групп всех пользователей
    emit('new_group', {
        'group_id': group_id,
        'group_name': group_name,
        'members': [creator]
    }, broadcast=True)

if __name__ == '__main__':
    print("🚀 NoknowGram Super Server запущен!")
    print("📞 Групповые звонки и чаты готовы!")
    print("🌐 Откройте: http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)