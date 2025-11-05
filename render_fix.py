import os
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
import hashlib
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'noknowgram-secret')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Создаем папку для загрузок
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# База данных
users_db = {}
messages_db = {'general': []}
online_users = {}

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'})
    
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    
    return jsonify({
        'success': True,
        'filename': filename,
        'url': f'/uploads/{filename}'
    })

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# WebSocket события
@socketio.on('connect')
def handle_connect():
    print("Client connected")

@socketio.on('send_message')
def handle_message(data):
    emit('new_message', data, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
