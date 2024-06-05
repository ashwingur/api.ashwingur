import random
import string
from flask import render_template, request
from app.tron import bp
from app.extensions import socketio, limiter, socket_rate_limit
from flask_socketio import emit, join_room, leave_room
import sys
from typing import Dict, Tuple, List

class Player:
    def __init__(self, sid: str, position: Tuple[int, int], direction: str) -> None:
        self.sid = sid
        self.colour = '#FFF'
        self.position = position
        self.direction = direction

    def set_colour(self, index: int):
        colour_map = {
            0: '#3ed9de',  # Blue
            1: '#cf7c34',  # Orange
            2: '#3bcc33',  # Green
            3: '#7033cc',  # Purple
            4: '#cc3333',  # Red
            5: '#cccc33'   # Yellow
        }
        self.colour = colour_map.get(index, '#FFFFFF')  # Default to white


class TronRoom:
    def __init__(self, max_players: int, room_code: str, grid_size: int=200) -> None:
        if max_players < 2:
            max_players = 2
        elif max_players > 4:
            max_players = 4
        self.max_players = max_players
        self.game_started = False
        self.players: List[Player] = []
        self.room_code = room_code
        self.grid_size = grid_size
        self.grid: List[List[str|None]] = None # Only initialise this when we're about to start the game

    def start_game(self):
        self.game_started = True
        self.grid = [[None for _ in range(self.grid_size)] for _ in range(self.grid_size)]
        # Initialize player colours
        for index, player in enumerate(self.players):
            player.set_colour(index) # Assign final colour
        self.init_player_position_and_direction()

    def init_player_position_and_direction(self):
        if len(self.players) == 2:
            # For 2 players start at opposite corners
            self.set_player_position(0, (20, 20), 'DOWN')
            self.set_player_position(1, (self.grid_size - 20, self.grid_size - 20), 'UP')
        elif len(self.players) == 3:
            # For 3 players start in corners as well
            self.set_player_position(0, (20, 20), 'DOWN')
            self.set_player_position(1, (self.grid_size - 20, self.grid_size - 20), 'UP')
            self.set_player_position(2, (20, self.grid_size - 20), 'RIGHT')
        elif len(self.players) == 4:
            # For 3 players start in corners as well
            self.set_player_position(0, (20, 20), 'DOWN')
            self.set_player_position(1, (self.grid_size - 20, self.grid_size - 20), 'UP')
            self.set_player_position(2, (20, self.grid_size - 20), 'RIGHT')
            self.set_player_position(3, (self.grid_size - 20, 20), 'LEFT')
    
    def set_player_position(self, index, position: Tuple[int, int], direction:str):
        if index < len(self.players) and direction in ['UP', 'DOWN', 'LEFT', 'RIGHT']:
            self.players[index].position = position
            self.players[index].direction = direction


    def __repr__(self) -> str:
        return f'Max players: {self.max_players}, players: {len(self.players)}, game_started: {self.game_started}'
    
    def serialise(self):
        return {
            'max_players': self.max_players,
            'players': [{'sid': p.sid, 'colour': p.colour, 'position': p.position, 'direction': p.direction} for p in self.players],
            'game_started': self.game_started,
            'room_code': self.room_code,
            'grid_size': self.grid_size
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
    emit('sid', {'sid': request.sid})

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

@socketio.on('create_room', namespace=NAMESPACE)
@socket_rate_limit(limit=15, window=60)
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
    # In case room code isn't unique (very unlikely but still possible)
    while room_code in rooms:
        room_code = generate_room_code()
    rooms[room_code] = TronRoom(max_players, room_code)
    join_room(room_code)
    new_player = Player(request.sid, (0, 0), 'UP')
    rooms[room_code].players.append(new_player)
    emit('join_room', {'success': True, 'room': rooms[room_code].serialise()})

@socketio.on('available_rooms', namespace=NAMESPACE)
def list_rooms():
    emit('available_rooms', {'rooms': [room.serialise() for _, room in rooms.items()], 'connected_users': connected_users})


@socketio.on('join_room', namespace=NAMESPACE)
@socket_rate_limit(limit=15, window=60)
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
        if any(player.sid == request.sid for player in room.players):
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
    if any(player.sid == request.sid for player in room.players):
        emit('join_room', {'success': False, 'error': "You are already in this room"})
        return
    join_room(code)
    new_player = Player(request.sid, (0, 0), 'UP')
    room.players.append(new_player)
    emit('join_room', {'success': True, 'room': room.serialise()})

    # If the room is full we can start the game!
    if len(room.players) == room.max_players:
        start_game(room)

@socketio.on('leave_room', namespace=NAMESPACE)
def my_leave_room():
    # Find the rooms the user is a part of and remove them from it
    rooms_to_delete = []
    for code, room in rooms.items():
        player_to_remove = next((player for player in room.players if player.sid == request.sid), None)
        if player_to_remove:
            room.players.remove(player_to_remove)
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
        player_to_remove = next((player for player in room.players if player.sid == request.sid), None)
        if player_to_remove:
            room.players.remove(player_to_remove)
            leave_room(code)
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
    emit('game_start', {'room': room.serialise(), 'countdown': 5}, room=room.room_code)
    socketio.sleep(5)  # Countdown
    run_game(room)

def run_game(room: TronRoom):
    collided_players = set()
    
    while room.game_started and len(collided_players) < len(room.players) - 1:
        for player in room.players:
            if player.sid in collided_players:
                continue

            new_position = list(player.position)
            if player.direction == 'UP':
                new_position[1] -= 1
            elif player.direction == 'DOWN':
                new_position[1] += 1
            elif player.direction == 'LEFT':
                new_position[0] -= 1
            elif player.direction == 'RIGHT':
                new_position[0] += 1

            # Wrap around grid boundaries
            new_position[0] %= room.grid_size
            new_position[1] %= room.grid_size

            # Check for collisions
            if room.grid[new_position[0]][new_position[1]] is not None:
                collided_players.add(player.sid)
                emit('collision', {'sid': player.sid, 'position': player.position}, room=room.room_code)
            else:
                # Update position and grid
                room.grid[player.position[0]][player.position[1]] = player.sid  # Mark old position
                player.position = tuple(new_position)
                room.grid[player.position[0]][player.position[1]] = player.sid  # Mark new position

        emit('game_tick', {'positions': {player.sid: player.position for player in room.players}}, room=room.room_code)
        socketio.sleep(1 / 30)  # 15 actions per second

    
    # We have a winner
    remaining_player = next((player for player in room.players if player.sid not in collided_players), None)
    if remaining_player is None:
        # Edge case where there's a tie (2 or more remaining players collided in the same tick)
        emit('game_over', {'tie': True},room=room.room_code)
    else:
        emit('game_over', {'winner': remaining_player.sid, 'colour': remaining_player.colour}, room=room.room_code)

    room.game_started = False

    # Make all players leave the room after some sleep
    socketio.sleep(2)
    for player in room.players:
        emit('leave_room', room=player.sid)
        leave_room(room.room_code, sid=player.sid)

    # Clean up the room
    del rooms[room.room_code]



@socketio.on('change_direction', namespace=NAMESPACE)
@socket_rate_limit(limit=10, window=1)
def change_direction(data: Dict[str, str]):
    room_code = data['room_code']
    direction = data['direction']
    
    if room_code in rooms:
        room = rooms[room_code]
        player = next((p for p in room.players if p.sid == request.sid), None)
        
        if player and direction in ['UP', 'DOWN', 'LEFT', 'RIGHT']:
            # Make sure the player doesnt try to turn more than 180 degrees at once
            if player.direction == 'UP' and direction == 'DOWN':
                return
            if player.direction == 'DOWN' and direction == 'UP':
                return
            if player.direction == 'LEFT' and direction == 'RIGHT':
                return
            if player.direction == 'RIGHT' and direction == 'LEFT':
                return
            player.direction = direction

