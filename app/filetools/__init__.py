from flask import Blueprint

bp = Blueprint('filetools', __name__)

from app.filetools import routes