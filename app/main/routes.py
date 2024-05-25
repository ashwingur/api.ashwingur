from flask import render_template, request, jsonify, make_response
from app.main import bp
from app.extensions import auth

@bp.route('/')
def index():
    return render_template('index.html')

users = {
    "admin": "poop",
    "user": "password"
}

@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username
    return None

@bp.route('/login', methods=['POST'])
@auth.login_required
def login():
    response = make_response(jsonify({"message": "Login successful"}))
    response.set_cookie('username', auth.username(), httponly=True)
    return response

@bp.route('/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({"message": "Logout successful"}))
    response.set_cookie('username', '', expires=0)
    return response

@bp.route('/checkauth', methods=['GET'])
def check_auth():
    username = request.cookies.get('username')
    if username and username in users:
        return jsonify({"authenticated": True, "username": username})
    return jsonify({"authenticated": False}), 401