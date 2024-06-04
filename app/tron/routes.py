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

    def __init__(self, max_players: int, room_code: str) -> None:
        if max_players < 2:
            max_players = 2
        elif max_players > 4:
            max_players = 4
        self.max_players = max_players
        self.game_started = False
        self.players = []
        self.room_code = room_code

    def __repr__(self) -> str:
        return f'Max players: {self.max_players}, players: {self.players}, game_started: {self.game_started}'
    
    def serialise(self):
        return {
            'max_players': self.max_players,
            'players': self.players,
            'game_started': self.game_started,
            'room_code': self.room_code
        }

        

NAMESPACE = '/tron'
rooms: Dict[str, TronRoom] = {}
connected_users = 0

@bp.route('/')
@limiter.limit("30/minute", override_defaults=True)
def index():
    return f"<h1>Tron game server<h1>"

@socketio.on('connect', namespace=NAMESPACE)
def client_connect():
    global connected_users
    connected_users += 1
    print(f"Client connected. Total connected users: {connected_users}", file=sys.stderr)

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@socketio.on('create_room', namespace=NAMESPACE)
def create_room(data: Dict[str, int]):
    '''
    Response template:
    {
        success: boolean;
        room?: Room;
        error?: string;
    }
    '''
    print(f"Create room called, {data}", file=sys.stderr)
    # Check if player is already in a room
    for code, room in rooms.items():
        if request.sid in room.players:
            emit('join_room', {'success': False, 'error': f'You are already in room {code}'})
            return

    max_players = data.get('max_players', 2)
    room_code = generate_room_code()
    # In case room code isn't unique (very unlikely but still)
    while room_code in rooms:
        room_code = generate_room_code()
    rooms[room_code] = TronRoom(max_players, room_code)
    join_room(room_code)
    rooms[room_code].players.append(request.sid)
    emit('join_room', {'success': True, 'room': rooms[room_code].serialise()})

@socketio.on('available_rooms', namespace=NAMESPACE)
def list_rooms():
    emit('available_rooms', {'rooms': [room.serialise() for _, room in rooms.items()], 'connected_users': connected_users})


@socketio.on('join_room', namespace=NAMESPACE)
def my_join_room(data: Dict[str, str]):
    '''
    Response template:
    {
        success: boolean;
        room?: Room;
        error?: string;
    }
    '''
    print(f"Join room called, {data}", file=sys.stderr)
        # Check if player is already in a room
    for code, room in rooms.items():
        if request.sid in room.players:
            emit('join_room', {'success': False, 'error': f'You are already in room {code}'})
            return

    code = data['room_code']
    if code not in rooms:
        emit('join_room', {'success': False, 'error': "Room does not exist"})
        return
    room = rooms[code]
    if len(room.players) >= room.max_players:
        emit('join_room', {'success': False, 'error': "Room is full"})
        return
    if request.sid in room.players:
        emit('join_room', {'success': False, 'error': "You are already in this room"})
        return
    join_room(code)
    room.players.append(request.sid)
    emit('join_room', {'success': True, 'room': room.serialise()})

@socketio.on('disconnect', namespace=NAMESPACE)
def client_disconnect():
    print(f"Client disconnected (SID: {request.sid})", file=sys.stderr)
    # Go through every room and clean up player if they're in a room
    global connected_users
    connected_users -= 1
    print(f"Client disconnected (SID: {request.sid}). Total connected users: {connected_users}", file=sys.stderr)
    rooms_to_delete = []
    for code, room in rooms.items():
        if request.sid in room.players:
            room.players.remove(request.sid)
            if len(room.players) == 0:
                rooms_to_delete.append(code)
    for code in rooms_to_delete:
        del rooms[code]

@socketio.on('connected_users', namespace=NAMESPACE)
def ping():
    emit('connected_users', {"connected_users": connected_users})

@socketio.on('ping', namespace=NAMESPACE)
def ping():
    print("PING received", file=sys.stderr)
    emit("pong")