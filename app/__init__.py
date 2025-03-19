import os

from flask import Flask, jsonify, request

from app.extensions import cors, db, limiter, login_manager, migrate, socketio
from app.middleware import register_middlewares
# Ensure the models are imported so its registered
from app.models.frontend_log import FrontendLog
from app.models.transportopendata import ParkingLot
from app.models.media_reviews import (Genre, MediaReview, MediaReviewGenre,
                                      SubMediaReview,
                                      create_example_reviews_and_genres,
                                      initialise_media_reviews)
from app.models.post import Post
from app.models.request_log import RequestLog
from app.models.user import create_admin_user
from app.models.weather_data import SensorData
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.secret_key = os.environ.get('FLASK_SECRET_KEY')

    # limiter.enabled = False

    # Initialise flask extensions
    # Initialise sqlalchemy db
    db.init_app(app)
    # Initialise flask migration
    migrate.init_app(app, db)
    # Configure scoped session

    # with app.app_context():
    #     initialise_media_reviews()

    #     db.create_all()

    # create_example_reviews_and_genres()
    # Create admin user here if needed

    # Intialise timescaledb HYPERTABLES
    from app.models.weather_data import setup_sensor_data_table
    setup_sensor_data_table()
    from app.models.request_log import setup_request_logs_table
    setup_request_logs_table()
    from app.models.frontend_log import setup_frontend_logs_table
    setup_frontend_logs_table()
    from app.models.transportopendata import set_parking_data_table
    # set_parking_data_table()

    # Initialise CORS for auth
    cors.init_app(app, resources={
                  r"/*": {"origins": "*", "supports_credentials": True}})
    # Initialise rate limiter
    limiter.init_app(app)
    # Initialise login manager
    login_manager.init_app(app)
    # Initialise websocket module
    socketio.init_app(app, cors_allowed_origins="*")

    # Register middlewares
    register_middlewares(app)

    # Register blueprints
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.posts import bp as posts_bp
    app.register_blueprint(posts_bp, url_prefix='/posts')

    from app.weather import bp as weather_bp
    app.register_blueprint(weather_bp, url_prefix='/weather')

    from app.tron import bp as tron_bp
    app.register_blueprint(tron_bp, url_prefix='/tron')

    from app.filetools import bp as filetools_bp
    app.register_blueprint(filetools_bp, url_prefix='/filetools')

    from app.analytics import bp as analytics_bp
    app.register_blueprint(analytics_bp, url_prefix='/analytics')

    from app.mediareviews import bp as mediareviews_bp
    app.register_blueprint(mediareviews_bp, url_prefix='/mediareviews')

    from app.transportopendata import bp as transportopendata_bp
    app.register_blueprint(transportopendata_bp,
                           url_prefix='/transportopendata')

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({"error": f"rate limit exceeded {e.description}"}), 429

    return app
