from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_httpauth import HTTPBasicAuth

db = SQLAlchemy()

cors = CORS()

auth = HTTPBasicAuth()

limiter = Limiter(
    get_remote_address,
    default_limits=["50 per hour"]
)
