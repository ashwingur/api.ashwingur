from flask import render_template, request, jsonify, make_response, abort
from app.main import bp
from app.extensions import limiter, login_manager
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from functools import wraps
import sys

@bp.route('/')
def index():
    return render_template('index.html')

# Example User class
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

    def has_role(self, *roles):
        return self.role in roles

users = {
    1: {'username': 'user1', 'password': 'password1', 'role': 'user'},
    2: {'username': 'admin', 'password': 'poop', 'role': 'admin'}
}

@login_manager.user_loader
def load_user(user_id):
    user_data = users.get(int(user_id))
    if user_data:
        return User(user_id, user_data['username'], user_data['role'])
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
            user = User(user_id, username, data['role'])
            login_user(user, remember=True)
            return jsonify({'message': 'Login successful','username': current_user.username}), 200

    return jsonify({'message': 'Invalid credentials'}), 401

@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logout successful'}), 200

@bp.route('/checkauth', methods=['GET'])
@limiter.exempt
def check_auth():
    if current_user.is_authenticated:
        return jsonify({'authenticated': True, 'id': current_user.id, 'username': current_user.username, 'role': current_user.role})
    else:
        return jsonify({'authenticated': False})
    
# Role required decorator
def roles_required(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            print(f'roles: {roles}, authenticated: {current_user.is_authenticated}, username: {current_user.username}, role: {current_user.role}', file=sys.stderr)
            if not current_user.is_authenticated or not current_user.has_role(*roles):
                abort(403)  # Forbidden
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

### TEST
@bp.route('/admin_test', methods=['GET'])
@login_required
@roles_required('admin')
def admin_dashboard():
    return jsonify({'message': 'Welcome to the admin dashboard', 'username': current_user.username})

@bp.route('/user_test', methods=['GET'])
@login_required
@roles_required('user', 'admin')
def user_dashboard():
    return jsonify({'message': 'Welcome to the user dashboard', 'username': current_user.username})
