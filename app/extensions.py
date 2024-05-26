from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_login import LoginManager

db = SQLAlchemy()

cors = CORS()

login_manager = LoginManager()

limiter = Limiter(
    get_remote_address,
    default_limits=["50 per hour"]
)
