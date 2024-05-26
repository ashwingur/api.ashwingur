from flask import render_template, request, jsonify, make_response, abort
from app.main import bp
from app.extensions import limiter, login_manager
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from functools import wraps
import sys
from app.models.user import User


@bp.route('/')
def index():
    return render_template('index.html')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@bp.route('/login', methods=['POST'])
@limiter.limit("10/minute", override_defaults=False)
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username).first()
    if user and user.password == password:
        login_user(user, remember=True)
        return jsonify({'message': 'Login successful', 'username': user.username}), 200

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
            # print(f'roles: {roles}, authenticated: {current_user.is_authenticated}, username: {current_user.username}, role: {current_user.role}', file=sys.stderr)
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
