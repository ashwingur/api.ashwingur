from functools import wraps
from flask import abort
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import psycopg2
from flask_cors import CORS
from flask_login import LoginManager, current_user
from config import Config

db = SQLAlchemy()

cors = CORS()

login_manager = LoginManager()

limiter = Limiter(
    get_remote_address,
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

