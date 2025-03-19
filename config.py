import os
import sys
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    FLASK_ENV = os.environ.get("FLASK_ENV")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DB_URL")
    REDIS_URL = os.environ.get("REDIS_URL")
    REMEMBER_COOKIE_DURATION = timedelta(days=60)
    PERMANENT_SESSION_LIFETIME = timedelta(days=60)
    IMGPROXY_KEY = os.environ.get("IMGPROXY_KEY")
    IMGPROXY_SALT = os.environ.get("IMGPROXY_SALT")
    OPEN_DATA_TOKEN = os.environ.get("OPEN_DATA_TOKEN")
    PARKING_POST_PASSWORD = os.environ.get("PARKING_POST_PASSWORD")
    WEATHER_POST_PASSWORD = os.environ.get("WEATHER_POST_PASSWORD")

