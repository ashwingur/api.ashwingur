from flask import Blueprint

bp = Blueprint('weather', __name__)

from app.weather import routes