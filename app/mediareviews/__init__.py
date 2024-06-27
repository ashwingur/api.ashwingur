from flask import Blueprint

bp = Blueprint('mediareviews', __name__)

from app.mediareviews import routes