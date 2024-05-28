from datetime import datetime
from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    date_registered = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login_timestamp = db.Column(db.DateTime)

    def has_role(self, *roles):
        return self.role in roles
    

def create_admin_user(username, password):
    new_user = User(username=username, password=generate_password_hash(password), role='admin')
    db.session.add(new_user)
    db.session.commit()