import random
import string
from flask import render_template, request
from app.tron import bp
from app.extensions import socketio, limiter
from flask_socketio import emit, join_room, leave_room
import sys
from typing import Dict

# CAN THIS ONLY WORK WITH 1 WORKER THREAD? OTHERWISE THEY CANT TALK TO EACH OTHER

class TronRoom:

    def __init__(self, max_players: int) -> None:
        if max_players < 2:
            max_players = 2
        elif max_players > 4:
            max_players = 4
        self.max_players = max_players
        self.game_started = False
        self.players = []

    def __repr__(self) -> str:
        return f'Max players: {self.max_players}, players: {self.players}, game_started: {self.game_started}'
    
    def serialise(self):
        return {
            'max_players': self.max_players,
            'players': self.players,
            'game_started': self.game_started
        }

        

NAMESPACE = '/tron'
rooms: Dict[str, TronRoom] = {}

@bp.route('/')
@limiter.limit("30/minute", override_defaults=True)
def index():
    return f"<h1>Tron game server<h1>"

@socketio.on('connect', namespace=NAMESPACE)
def local_client_connect():
    print("Client connected", file=sys.stderr)

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@socketio.on('create_room', namespace=NAMESPACE)
def create_room(data: Dict[str, int]):
    print(f"Create room called, {data}", file=sys.stderr)
    max_players = data.get('max_players', 2)
    room_code = generate_room_code()
    while room_code in rooms:
        room_code = generate_room_code()
    rooms[room_code] = TronRoom(max_players)
    join_room(room_code)
    rooms[room_code].players.append(request.sid)
    emit('room_created', {'room_code': room_code})

@socketio.on('available_rooms', namespace=NAMESPACE)
def list_rooms():
    emit('rooms_list', {'message': {code: room.serialise() for code, room in rooms.items()}})

@socketio.on('join_room', namespace=NAMESPACE)
def my_join_room(data: Dict[str, str]):
    print(f"Join room called, {data}", file=sys.stderr)
    code = data['room_code']
    if code not in rooms:
        emit('error', {'message': "invalid room"})
        return
    room = rooms[code]
    if len(room.players) >= room.max_players:
        emit('error', {'message': "room is full!"})
        return
    if request.sid in room.players:
        emit('error', {'message': "you are already in this room!"})
        return
    join_room(code)
    room.players.append(request.sid)
    emit('room_joined', {'room_code': code, 'message': {code: room.serialise() for code, room in rooms.items()}})

@socketio.on('disconnect', namespace=NAMESPACE)
def local_client_connect():
    print("Client disconnected", file=sys.stderr)

@socketio.on('ping', namespace=NAMESPACE)
def ping():
    print("PING received", file=sys.stderr)
    emit("pong")