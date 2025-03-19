from flask import Blueprint

bp = Blueprint('transportopendata', __name__)

from app.transportopendata import routes