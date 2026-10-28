import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError('Set SECRET_KEY to a long, random value before starting Paskibra.')
    DATABASE = os.path.join(os.getcwd(), 'paskibra_v2.db')
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    
    # System Settings
    APP_NAME = 'Paskibra'
    VERSION = '2.1.12'

    # Persistent Login Settings
    PERMANENT_SESSION_LIFETIME = 365 * 24 * 60 * 60  # 1 year in seconds
    SESSION_REFRESH_EACH_REQUEST = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
