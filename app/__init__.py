from flask import Flask

from config import Config
from app.extensions import db, limiter, cors, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.secret_key = "some_secret_key"

    # Initialise flask extensions
    # Initialise sqlalchemy db
    db.init_app(app)
    with app.app_context():
        from app.models.post import Post
        from app.models.user import User
        db.create_all()
    # Initialise CORS for auth
    cors.init_app(app, supports_credentials=True)
    # Initialise rate limiter
    limiter.init_app(app)
    # Initialise login manager
    login_manager.init_app(app)

    # Register blueprints
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)
    
    from app.posts import bp as posts_bp
    app.register_blueprint(posts_bp, url_prefix='/posts')

    @app.route('/test/')
    @limiter.limit("1/second", override_defaults=False)
    def test_page():
        return '<h1>Hello, world!!!</h1>'
    
    return app