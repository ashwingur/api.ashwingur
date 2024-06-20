from flask import request, Flask
from datetime import datetime
from app.models.request_log import RequestLog
from app.extensions import db
from zoneinfo import ZoneInfo

def log_request():
    if request.endpoint != 'static':
        timestamp = datetime.now(ZoneInfo("UTC"))

        # Get the client IP address from the request headers
        user_ip = request.headers.get('X-Real-IP', request.remote_addr)
        
        endpoint = request.endpoint
        method = request.method

        log_entry = RequestLog(user_ip=user_ip, endpoint=endpoint, method=method, timestamp=timestamp)
        db.session.add(log_entry)
        db.session.commit()

def register_middlewares(app: Flask):
    app.before_request(log_request)
