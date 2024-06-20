from flask import Flask
import os
from config import Config
from app.extensions import db, limiter, cors, login_manager, socketio
from app.middleware import register_middlewares
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.secret_key = os.environ.get('FLASK_SECRET_KEY')

    # Apply ProxyFix, this will allow unique users to be monitored
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)


    # Initialise flask extensions
    # Initialise sqlalchemy db
    db.init_app(app)
    with app.app_context():
        from app.models.user import create_admin_user
        # REMOVE THIS AFTER BECAUSE IT CAN WIPE THE WHOLE DB
        # User.__table__.drop(db.engine)
        db.create_all()
        # Create admin user here if needed
    # Initialise sensor data table if it doesn't exist (this uses timescale db)
    from app.models.weather_data import setup_sensor_data_table
    setup_sensor_data_table()
    # Initialise analytics table if it doesnt exist
    from app.models.request_log import setup_request_logs_table
    setup_request_logs_table()

    # Initialise CORS for auth
    cors.init_app(app, resources={r"/*": {"origins": "*", "supports_credentials": True}})
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
    
    return app