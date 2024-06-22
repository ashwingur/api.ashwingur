from functools import wraps
from flask import abort, request
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import psycopg2
from flask_cors import CORS
from flask_login import LoginManager, current_user
from config import Config
from flask_socketio import SocketIO, emit
from redis import Redis
import sys

db = SQLAlchemy()

cors = CORS()

login_manager = LoginManager()

socketio = SocketIO()

# Custom function to get the real IP address
def get_real_ip():
    if request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For can contain multiple IP addresses, we need the first one
        print(f"X-forwardedfor is {request.headers.get('X-Forwarded-For')}", file=sys.stderr)
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    print(f"X-remote is {request.remote_addr}", file=sys.stderr)
    return request.remote_addr

limiter = Limiter(
    # get_remote_address,
    get_real_ip,
    default_limits=["50 per hour"],
    storage_uri=Config.REDIS_URL
)


def psycop_conn():
    return psycopg2.connect(Config.SQLALCHEMY_DATABASE_URI)


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


redis_client = Redis.from_url(Config.REDIS_URL)

def socket_rate_limit(limit: int=15, window: int=60):
    """
    Custom rate limiter for Socket.IO events.

    :param limit: Number of allowed requests within the time window.
    :param window: Time window in seconds.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            remote_address = request.remote_addr
            key = f"rl:{remote_address}:{f.__name__}"
            current = redis_client.get(key)

            if current and int(current) >= limit:
                emit('rate_limit_exceeded', {'message': 'Rate limit exceeded. Try again later.'})
                return

            if not current:
                redis_client.set(key, 1, ex=window)
            else:
                redis_client.incr(key)

            return f(*args, **kwargs)

        return wrapped

    return decorator