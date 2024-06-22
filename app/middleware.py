import sys
import uuid
from flask import g, make_response, request, Flask
from datetime import datetime
from app.models.request_log import RequestLog
from app.extensions import db, get_real_ip
from zoneinfo import ZoneInfo

def set_user_id():
    user_id = request.cookies.get('user_id')
    if not user_id:
        user_id = str(uuid.uuid4())
        g.new_user_id = user_id  # Store in g to use later in the response
    else:
        g.new_user_id = None
    g.user_id = user_id

def log_request():
    if request.endpoint != 'static':
        timestamp = datetime.now(ZoneInfo("UTC"))
        user_id = g.user_id
        endpoint = request.endpoint
        method = request.method
        user_ip = get_real_ip()

        log_entry = RequestLog(user_id=user_id, user_ip=user_ip, endpoint=endpoint, method=method, timestamp=timestamp)
        db.session.add(log_entry)
        db.session.commit()

def set_user_cookie(response):
    if g.get('new_user_id'):
        response.set_cookie('user_id', g.new_user_id)
    return response

def register_middlewares(app: Flask):
    app.before_request(set_user_id)
    app.before_request(log_request)
    app.after_request(set_user_cookie)
