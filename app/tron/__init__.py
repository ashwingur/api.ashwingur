from flask import Blueprint

bp = Blueprint('tron', __name__)

from app.tron import routes