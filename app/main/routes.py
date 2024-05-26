from flask import render_template, request, jsonify, make_response
from app.main import bp
from app.extensions import limiter, login_manager
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
import sys

@bp.route('/')
def index():
    return render_template('index.html')

# Example User class
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

users = {
    1: {'username': 'user1', 'password': 'password1'},
    2: {'username': 'admin', 'password': 'poop'}
}

@login_manager.user_loader
def load_user(user_id):
    user_data = users.get(int(user_id))
    if user_data:
        return User(user_id, user_data['username'])
    return None

def verify_password(username, password):
    if username in users and users[username] == password:
        return username
    return None

@bp.route('/login', methods=['POST'])
@limiter.limit("10/minute", override_defaults=False)
def login():
    username = request.json.get('username')
    password = request.json.get('password')

    user = None
    for user_id, data in users.items():
        if data['username'] == username and data['password'] == password:
            user = User(user_id, username)
            login_user(user)
            return jsonify({'message': 'Login successful'}), 200

    return jsonify({'message': 'Invalid credentials'}), 401

@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    print(f"logout called", file=sys.stderr)
    logout_user()
    return jsonify({'message': 'Logout successful'}), 200

@bp.route('/checkauth', methods=['GET'])
@limiter.exempt
def check_auth():
    # print(f"Received auth {current_user.is_authenticated}", file=sys.stderr)
    if current_user.is_authenticated:
        return jsonify({'authenticated': True, 'id': current_user.id, 'username': current_user.username})
    else:
        return jsonify({'authenticated': False})