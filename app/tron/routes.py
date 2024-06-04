from flask import render_template
from app.tron import bp
from app.extensions import socketio
from flask_socketio import emit
import sys

NAMESPACE = '/tron'

@bp.route('/')
def index():
    return "Tron game server"

@socketio.on('connect')
def local_client_connect():
    print("Client connected", file=sys.stderr)
    emit('pong', {"data": "connection received"})

@socketio.on('disconnect')
def local_client_connect():
    print("Client disconnected", file=sys.stderr)

@socketio.on('ping')
def ping():
    print("PING received", file=sys.stderr)
    emit("pong")