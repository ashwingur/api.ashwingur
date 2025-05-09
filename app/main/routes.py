import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import app, jsonify, render_template, request
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import (db, get_real_ip, limiter, login_manager,
                            roles_required)
from app.image_proxy import ImageProxy
from app.main import bp
from app.models.user import User

POSSIBLE_ROLES = ['user', 'admin']


@bp.route('/')
def index():
    return render_template('index.html')


@bp.route('/imagetest')
def image_test():
    # return ImageProxy.sign_image_url("https://letsenhance.io/static/8f5e523ee6b2479e26ecc91b9c25261e/1015f/MainAfter.jpg", format='avif')
    return ImageProxy.sign_image_url("local:///downloaded_image.jpg", format='avif')

@bp.route("/downloadimage")
def download_and_save_image_test():
    image_url = 'https://static.vecteezy.com/system/resources/thumbnails/036/324/708/small/ai-generated-picture-of-a-tiger-walking-in-the-forest-photo.jpg'
    filename = 'downloaded_image.jpg'
    
    try:
        saved_image_path = ImageProxy.download_image(image_url, filename)
        return jsonify({"message": f"Image saved at {saved_image_path}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@bp.route('/ip')
def ip():
    ip = get_real_ip()
    return f"<h1>Your IP: {ip}</h1>"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@bp.route('/users', methods=['GET', 'POST', 'DELETE'])
@limiter.limit("30/minute", override_defaults=True)
@login_required
@roles_required('admin')
def users():
    if request.method == 'GET':
        # Return all users from the database with all data except password
        users: list[User] = User.query.all()
        user_list = [{'id': user.id, 'username': user.username, 'role': user.role,
                      'date_registered': user.date_registered, 'last_login': user.last_login_timestamp} for user in users]
        return jsonify(user_list), 200

    elif request.method == 'POST':
        # Create a new user. The signup provides username, password and role
        data = request.json
        username = data.get('username')
        password = data.get('password')
        # Assuming role is provided in the request body
        role = data.get('role')

        if role != "user":
            return jsonify({'error': 'Only user role can be created'}), 403

        if not username or not password or not role:
            return jsonify({'message': 'Username, password, and role are required'}), 400
        if role not in POSSIBLE_ROLES:
            return jsonify({'message': f"'{role}' is not a valid role"}), 400

        if User.query.filter_by(username=username).first():
            return jsonify({'message': 'Username already exists'}), 409

        new_user = User(username=username,
                        password=generate_password_hash(password), role=role)
        db.session.add(new_user)
        db.session.commit()

        return jsonify({'message': 'User created successfully', 'username': username}), 201

    elif request.method == 'DELETE':
        # Delete a user by ID
        data = request.json
        user_id = data.get('id')

        if not user_id:
            return jsonify({'message': 'User ID is required'}), 400

        user_to_delete = User.query.get(user_id)

        if not user_to_delete:
            return jsonify({'message': 'User not found'}), 404

        # Ensure admin cannot delete themselves
        if user_to_delete == current_user:
            return jsonify({'message': 'Admin cannot delete themselves'}), 403

        deleted_username = user_to_delete.username

        db.session.delete(user_to_delete)
        db.session.commit()

        return jsonify({'message': f"User '{deleted_username}' deleted successfully"}), 200


@bp.route('/login', methods=['POST'])
@limiter.limit("10/minute", override_defaults=False)
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password, password):
        login_user(user, remember=True)
        user.last_login_timestamp = datetime.now(ZoneInfo("UTC"))
        db.session.commit()
        response = jsonify(
            {'authenticated': True, 'username': user.username, 'role': user.role})

        return response, 200

    return jsonify({'message': 'Invalid credentials', 'authenticated': False}), 401


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

# TEST


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
