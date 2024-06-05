import random
import string
from flask import render_template, request
from app.tron import bp
from app.extensions import socketio, limiter
from flask_socketio import emit, join_room, leave_room
import sys
from typing import Dict, Tuple, List

class TronRoom:
    def __init__(self, max_players: int, room_code: str) -> None:
        if max_players < 2:
            max_players = 2
        elif max_players > 4:
            max_players = 4
        self.max_players = max_players
        self.game_started = False
        self.players: List[str] = []
        self.room_code = room_code
        self.player_positions: Dict[str, Tuple[int, int]] = {}
        self.player_directions: Dict[str, str] = {}

    def start_game(self):
        self.game_started = True
        # Initialize player positions and directions
        for player in self.players:
            self.player_positions[player] = (0, 0)  # Starting positions
            self.player_directions[player] = 'UP'  # Starting direction

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
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

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

    # If the room is full we can start the game!
    if len(room.players) == room.max_players:
        start_game(room)

@socketio.on('leave_room', namespace=NAMESPACE)
def my_leave_room():
    # Find the rooms the user is a part of and remove them from it
    rooms_to_delete = []
    for code, room in rooms.items():
        if request.sid in room.players:
            room.players.remove(request.sid)
            if len(room.players) == 0:
                rooms_to_delete.append(code)
            leave_room(code)
    for code in rooms_to_delete:
        del rooms[code]
    emit('leave_room')


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
            leave_room(code)
            room.players.remove(request.sid)
            if len(room.players) == 0:
                rooms_to_delete.append(code)
    for code in rooms_to_delete:
        del rooms[code]

@socketio.on('connected_users', namespace=NAMESPACE)
def ping():
    emit('connected_users', {"connected_users": connected_users})

@socketio.on('ping', namespace=NAMESPACE)
def ping(data):
    emit("pong", data)

def start_game(room: TronRoom):
    room.start_game()
    emit('game_start', {'room': room.serialise(), 'countdown': 3}, room=room.room_code)
    socketio.sleep(3)  # Countdown
    run_game(room)

def run_game(room: TronRoom):
    while room.game_started and room.players:
        for player in room.players:
            if room.player_directions[player] == 'UP':
                room.player_positions[player] = (room.player_positions[player][0], room.player_positions[player][1] - 1)
            elif room.player_directions[player] == 'DOWN':
                room.player_positions[player] = (room.player_positions[player][0], room.player_positions[player][1] + 1)
            elif room.player_directions[player] == 'LEFT':
                room.player_positions[player] = (room.player_positions[player][0] - 1, room.player_positions[player][1])
            elif room.player_directions[player] == 'RIGHT':
                room.player_positions[player] = (room.player_positions[player][0] + 1, room.player_positions[player][1])

        emit('game_tick', {'positions': room.player_positions}, room=room.room_code)
        socketio.sleep(1 / 15)  # 15 actions per second

@socketio.on('change_direction', namespace=NAMESPACE)
def change_direction(data: Dict[str, str]):
    room_code = data['room_code']
    direction = data['direction']
    if room_code in rooms and request.sid in rooms[room_code].players:
        if direction in ['UP', 'DOWN', 'LEFT', 'RIGHT']:
            rooms[room_code].player_directions[request.sid] = direction
