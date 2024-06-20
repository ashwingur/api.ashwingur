import sys
from flask import request, Flask
from datetime import datetime
from app.models.request_log import RequestLog
from app.extensions import db
from zoneinfo import ZoneInfo

def log_request():
    if request.endpoint != 'static':
        timestamp = datetime.now(ZoneInfo("UTC"))

        # Get the client IP address from the request headers
        x_real_ip = request.headers.get('X-Real-IP')
        x_forwarded_for = request.headers.get('X-Forwarded-For')

        if x_forwarded_for:
            user_ip = x_forwarded_for.split(',')[0]
        elif x_real_ip:
            user_ip = x_real_ip
        else:
            user_ip = request.remote_addr

        # Debug log to verify headers and IPs
        print(f"X-Real-IP: {x_real_ip}", file=sys.stderr)
        print(f"X-Forwarded-For: {x_forwarded_for}", file=sys.stderr)
        print(f"Captured IP: {user_ip}\n", file=sys.stderr)

        endpoint = request.endpoint
        method = request.method

        log_entry = RequestLog(user_ip=user_ip, endpoint=endpoint, method=method, timestamp=timestamp)
        db.session.add(log_entry)
        db.session.commit()

def register_middlewares(app: Flask):
    app.before_request(log_request)
