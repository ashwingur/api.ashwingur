from flask import Blueprint

bp = Blueprint('clashofclans', __name__)

from app.clashofclans import routes