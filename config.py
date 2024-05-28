import os, sys
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DB_URL")
    REMEMBER_COOKIE_DURATION = timedelta(days=1)
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)