import os
import datetime
import jwt
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# MongoDB Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/friday-db")
client = MongoClient(MONGODB_URI)

def get_database_name(uri, default="friday-db"):
    try:
        path = uri.split("://", 1)[-1]
        if "/" in path:
            db_and_options = path.split("/", 1)[-1]
            db_name = db_and_options.split("?", 1)[0]
            if db_name:
                return db_name
    except Exception:
        pass
    return default

db_name = get_database_name(MONGODB_URI)
db = client[db_name]

# JWT Secret
JWT_SECRET = os.getenv("JWT_SECRET", "friday_jwt_secret_key_2026_super_secure")

# ── JWT AUTH DECORATOR ──
def token_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({'error': 'Access token required'}), 401
        
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            current_user = data['email']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 403
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid or expired token'}), 403
        
        return f(current_user, *args, **kwargs)
    return decorated

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.datetime.utcnow().isoformat()}), 200

# ── SERVE FRONTEND STATIC FILES ──
@app.route('/')
def serve_index():
    return send_from_directory('.', 'login.html')

@app.route('/login.html')
def serve_login():
    return send_from_directory('.', 'login.html')

@app.route('/main.html')
def serve_main():
    return send_from_directory('.', 'main.html')

@app.route('/chat.html')
def serve_chat():
    return send_from_directory('.', 'chat.html')

# Fallback to serve static assets (js, css, images)
@app.route('/<path:path>')
def serve_assets(path):
    return send_from_directory('.', path)

# ── AUTHENTICATION ROUTE ──
@app.post('/api/auth/login')
def api_login():
    try:
        data = request.get_json() or {}
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        user = db.users.find_one({'email': email})
        
        if not user:
            # Auto-register new user
            hashed_pw = generate_password_hash(password)
            db.users.insert_one({
                'email': email,
                'password': hashed_pw,
                'createdAt': datetime.datetime.utcnow()
            })
            print(f"Auto-registered new user in Flask: {email}", flush=True)
        else:
            # Verify password
            try:
                if not check_password_hash(user['password'], password):
                    return jsonify({'error': 'Invalid password'}), 400
            except ValueError:
                # If old bcrypt Node hash, upgrade it to Werkzeug hash
                hashed_pw = generate_password_hash(password)
                db.users.update_one({'_id': user['_id']}, {'$set': {'password': hashed_pw}})
                print(f"Upgraded password hash type to Werkzeug for user: {email}", flush=True)
        
        # Sign JWT Token
        payload = {
            'email': email,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        
        return jsonify({
            'token': token,
            'email': email
        })
        
    except Exception as e:
        print("Login error in Flask:", e)
        return jsonify({'error': 'Internal server error'}), 500

@app.get('/api/auth/verify')
@token_required
def api_verify(current_user):
    return jsonify({'valid': True, 'email': current_user})

# ── PROJECT ROUTES ──

# List projects
@app.get('/api/projects')
@token_required
def get_projects(current_user):
    try:
        projects_cursor = db.projects.find({'userEmail': current_user}).sort('createdAt', -1)
        projects = []
        for p in projects_cursor:
            projects.append({
                '_id': str(p['_id']),
                'name': p['name'],
                'description': p.get('description', ''),
                'createdAt': p.get('createdAt', '').isoformat() if isinstance(p.get('createdAt'), datetime.datetime) else str(p.get('createdAt', ''))
            })
        return jsonify(projects)
    except Exception as e:
        print("Error getting projects:", e)
        return jsonify({'error': 'Internal server error'}), 500

# Create project
@app.post('/api/projects/create')
@token_required
def create_project(current_user):
    try:
        data = request.get_json() or {}
        name = data.get('name')
        description = data.get('description', '')
        
        if not name:
            return jsonify({'error': 'Project name is required'}), 400
        
        result = db.projects.insert_one({
            'name': name,
            'description': description,
            'userEmail': current_user,
            'createdAt': datetime.datetime.utcnow()
        })
        
        return jsonify({
            '_id': str(result.inserted_id),
            'name': name,
            'description': description
        }), 201
    except Exception as e:
        print("Error creating project:", e)
        return jsonify({'error': 'Internal server error'}), 500

# Delete project
@app.delete('/api/projects/<project_id>')
@token_required
def delete_project(current_user, project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({'error': 'Invalid project ID'}), 400
            
        result = db.projects.delete_one({'_id': ObjectId(project_id), 'userEmail': current_user})
        if result.deleted_count == 0:
            return jsonify({'error': 'Project not found'}), 404
            
        # Unlink chat sessions associated with this deleted project
        db.chatsessions.update_many(
            {'projectId': ObjectId(project_id), 'userEmail': current_user},
            {'$set': {'projectId': None}}
        )
        return jsonify({'success': True, 'message': 'Project deleted'})
    except Exception as e:
        print("Error deleting project:", e)
        return jsonify({'error': 'Internal server error'}), 500

# ── CHAT HISTORY ROUTES ──

# List chat sessions
@app.get('/api/chat/sessions')
@token_required
def get_sessions(current_user):
    try:
        sessions_cursor = db.chatsessions.find({'userEmail': current_user}).sort('updatedAt', -1)
        sessions = []
        for s in sessions_cursor:
            sessions.append({
                '_id': str(s['_id']),
                'title': s.get('title', 'New Chat'),
                'projectId': str(s['projectId']) if s.get('projectId') else None,
                'updatedAt': s.get('updatedAt', '').isoformat() if isinstance(s.get('updatedAt'), datetime.datetime) else str(s.get('updatedAt', ''))
            })
        return jsonify(sessions)
    except Exception as e:
        print("Error getting sessions:", e)
        return jsonify({'error': 'Internal server error'}), 500

# Get specific session details (messages)
@app.get('/api/chat/sessions/<session_id>')
@token_required
def get_session_details(current_user, session_id):
    try:
        if not ObjectId.is_valid(session_id):
            return jsonify({'error': 'Invalid session ID'}), 400
            
        session = db.chatsessions.find_one({'_id': ObjectId(session_id), 'userEmail': current_user})
        if not session:
            return jsonify({'error': 'Chat session not found'}), 404
            
        # Convert ObjectId & Date to string
        serialized_messages = []
        for m in session.get('messages', []):
            serialized_messages.append({
                'role': m['role'],
                'content': m['content'],
                'timestamp': m.get('timestamp', '').isoformat() if isinstance(m.get('timestamp'), datetime.datetime) else str(m.get('timestamp', ''))
            })
            
        return jsonify({
            '_id': str(session['_id']),
            'title': session.get('title', 'New Chat'),
            'projectId': str(session['projectId']) if session.get('projectId') else None,
            'messages': serialized_messages
        })
    except Exception as e:
        print("Error getting session details:", e)
        return jsonify({'error': 'Internal server error'}), 500

# Delete chat session
@app.delete('/api/chat/sessions/<session_id>')
@token_required
def delete_session(current_user, session_id):
    try:
        if not ObjectId.is_valid(session_id):
            return jsonify({'error': 'Invalid session ID'}), 400
            
        result = db.chatsessions.delete_one({'_id': ObjectId(session_id), 'userEmail': current_user})
        if result.deleted_count == 0:
            return jsonify({'error': 'Chat session not found'}), 404
        return jsonify({'success': True, 'message': 'Chat session deleted'})
    except Exception as e:
        print("Error deleting session:", e)
        return jsonify({'error': 'Internal server error'}), 500

# ── AI CHAT ROUTE (Groq Integration) ──
@app.post('/api/chat/message')
@token_required
def api_chat_message(current_user):
    try:
        data = request.get_json() or {}
        message = data.get('message')
        session_id = data.get('sessionId')
        project_id = data.get('projectId')
        
        if not message or message.strip() == '':
            return jsonify({'error': 'Message content is required'}), 400
            
        # 1. Fetch or create chat session
        session = None
        if session_id and ObjectId.is_valid(session_id):
            session = db.chatsessions.find_one({'_id': ObjectId(session_id), 'userEmail': current_user})
            
        if not session:
            title = message.strip().split(' ')
            title = ' '.join(title[:5]) + ('...' if len(title) > 5 else '')
            proj_obj_id = ObjectId(project_id) if project_id and ObjectId.is_valid(project_id) else None
            
            result = db.chatsessions.insert_one({
                'title': title,
                'userEmail': current_user,
                'projectId': proj_obj_id,
                'messages': [],
                'createdAt': datetime.datetime.utcnow(),
                'updatedAt': datetime.datetime.utcnow()
            })
            session = db.chatsessions.find_one({'_id': result.inserted_id})
            
        # Append User Message to session messages list
        user_msg = {
            'role': 'user',
            'content': message,
            'timestamp': datetime.datetime.utcnow()
        }
        db.chatsessions.update_one(
            {'_id': session['_id']},
            {
                '$push': {'messages': user_msg},
                '$set': {'updatedAt': datetime.datetime.utcnow()}
            }
        )
        
        # Reload session messages
        session = db.chatsessions.find_one({'_id': session['_id']})
        
        # 2. Intercept mock image requests
        lower_msg = message.lower().strip()
        if lower_msg.startswith('create an image of') or lower_msg.startswith('generate an image of') or lower_msg.startswith('draw a'):
            keyword = message.replace('create an image of', '').replace('generate an image of', '').replace('draw a', '').strip()
            if not keyword:
                keyword = 'beautiful scene'
            
            image_url = f"https://loremflickr.com/600/400/{requests.utils.quote(keyword)}"
            ai_response = f"Here is the image I generated for **\"{keyword}\"**:\n\n![{keyword}]({image_url})\n\nHope you like it! Let me know if you want any modifications."
        else:
            # 3. Call Groq Cloud API
            groq_api_key = os.getenv("GROQ_API_KEY")
            
            if not groq_api_key or groq_api_key == 'gsk_your_actual_groq_api_key_here' or groq_api_key.strip() == '':
                ai_response = "Friday AI is ready! Please configure your **GROQ_API_KEY** in the `.env` file of your project backend to start chatting with me."
            else:
                # Prepare conversation history for LLM
                system_prompt = {
                    'role': 'system',
                    'content': 'You are Friday AI, a smart, friendly, and helpful AI assistant. Answer user queries clearly, concisely, and accurately using beautiful markdown layout. Use emojis where appropriate to keep it engaging.'
                }
                
                messages_for_groq = [system_prompt]
                for m in session.get('messages', []):
                    messages_for_groq.append({
                        'role': 'assistant' if m['role'] in ['nexa', 'friday'] else 'user',
                        'content': m['content']
                    })
                
                # Fetch Groq completions
                try:
                    headers = {
                        "Authorization": f"Bearer {groq_api_key}",
                        "Content-Type": "application/json"
                    }
                    body = {
                        "model": "llama-3.1-8b-instant",  # Active Llama 3.1 model on Groq
                        "messages": messages_for_groq,
                        "temperature": 0.7,
                        "max_tokens": 1024,
                        "stream": False
                    }
                    response = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers,
                        json=body,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        ai_response = response.json()['choices'][0]['message']['content']
                    else:
                        print(f"Groq API Error: {response.status_code} - {response.text}", flush=True)
                        try:
                            err_msg = response.json().get('error', {}).get('message', 'Unknown Error')
                        except:
                            err_msg = response.text
                        ai_response = f"I had an issue getting a response from Groq. (API Error {response.status_code}: {err_msg})"
                except Exception as err:
                    print("Error calling Groq API:", err)
                    ai_response = "I encountered a connection error while trying to reach my AI brain. Please check your internet connection."

        # Append AI Message to Database
        ai_msg = {
            'role': 'friday',
            'content': ai_response,
            'timestamp': datetime.datetime.utcnow()
        }
        db.chatsessions.update_one(
            {'_id': session['_id']},
            {
                '$push': {'messages': ai_msg},
                '$set': {'updatedAt': datetime.datetime.utcnow()}
            }
        )
        
        return jsonify({
            'sessionId': str(session['_id']),
            'title': session.get('title', 'New Chat'),
            'response': ai_response
        })
        
    except Exception as e:
        print("Chat message error in Flask:", e)
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    # We set host to 0.0.0.0 to listen on all interfaces
    print(f"Friday AI Flask Server starting at http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
