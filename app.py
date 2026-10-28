from flask import Flask, render_template, g, session, redirect, url_for, abort, send_file
from config import Config
from database import init_db, close_connection, get_db
import os
import gzip
import hashlib
import tempfile
from time import monotonic
from flask import request

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.setdefault('SEND_FILE_MAX_AGE_DEFAULT', 60 * 60 * 24 * 30)
    app.extensions['maintenance_mode_cache'] = {'checked_at': 0.0, 'enabled': False}

    # Initialize Database
    init_db(app)
    app.teardown_appcontext(close_connection)

    # Register Blueprints
    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.admin import admin_bp
    from blueprints.attendance import attendance_bp
    from blueprints.profile import profile_bp
    from blueprints.schedule import schedule_bp
    from blueprints.members import members_bp
    from blueprints.notifications import notifications_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(notifications_bp)

    @app.url_defaults
    def version_static_assets(endpoint, values):
        if endpoint == 'static':
            values.setdefault('v', app.config['VERSION'])

    @app.route('/media/avatar/<filename>', endpoint='media_avatar')
    def media_avatar(filename):
        # Keep original uploads intact and serve small, metadata-free WebP copies
        # for the many 36–80px avatar slots throughout the UI.
        from werkzeug.utils import secure_filename
        if secure_filename(filename) != filename:
            abort(404)
        source = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.isfile(source):
            abort(404)

        stat = os.stat(source)
        cache_key = hashlib.sha256(
            f'{filename}:{stat.st_mtime_ns}:{stat.st_size}'.encode('utf-8')
        ).hexdigest()[:24]
        cache_dir = os.path.join(app.config['UPLOAD_FOLDER'], '.optimized')
        os.makedirs(cache_dir, exist_ok=True)
        optimized = os.path.join(cache_dir, f'{cache_key}.webp')

        if not os.path.isfile(optimized):
            from PIL import Image, ImageOps
            try:
                with Image.open(source) as original:
                    image = ImageOps.exif_transpose(original)
                    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
                    mode = 'RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB'
                    image = image.convert(mode)
                    with tempfile.NamedTemporaryFile(
                        dir=cache_dir, suffix='.webp', delete=False
                    ) as temp_file:
                        temp_path = temp_file.name
                    try:
                        image.save(temp_path, 'WEBP', quality=72, method=4)
                        os.replace(temp_path, optimized)
                    finally:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
            except (OSError, ValueError, Image.DecompressionBombError):
                # A malformed or unsupported upload falls back to the original.
                return send_file(source, conditional=True, max_age=60 * 60)

        return send_file(
            optimized, mimetype='image/webp', conditional=True,
            max_age=60 * 60 * 24 * 365
        )

    @app.after_request
    def optimize_response(response):
        compressible_types = {
            'text/html', 'text/css', 'text/plain', 'text/javascript',
            'application/javascript', 'application/json', 'application/xml',
            'image/svg+xml'
        }
        # Versioned asset URLs are immutable, so browsers can safely retain them
        # for a year and fetch new app assets as soon as VERSION changes.
        if request.endpoint == 'static' and request.args.get('v'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'

        # Compress textual responses only; photos and already-compressed files
        # gain little and would spend CPU for no transfer savings.
        if response.mimetype in compressible_types:
            if response.direct_passthrough:
                response.direct_passthrough = False
            vary = response.headers.get('Vary', '')
            if vary != '*' and 'accept-encoding' not in vary.lower():
                response.headers.add('Vary', 'Accept-Encoding')
        if (
            request.method != 'HEAD'
            and 200 <= response.status_code < 300
            and response.status_code not in (204, 206)
            and not response.direct_passthrough
            and not response.headers.get('Content-Encoding')
            and request.accept_encodings.quality('gzip')
            and response.mimetype in compressible_types
        ):
            body = response.get_data()
            if len(body) >= 1024:
                response.set_data(gzip.compress(body, compresslevel=6, mtime=0))
                response.headers['Content-Encoding'] = 'gzip'
                response.headers.pop('ETag', None)
        return response

    @app.route('/manifest.json')
    def manifest():
        return app.send_static_file('manifest.json')

    @app.route('/sw.js')
    def sw():
        response = app.send_static_file('js/sw.js')
        response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        return response

    @app.route('/offline')
    def offline():
        return render_template('offline.html')

    @app.context_processor
    def inject_now():
        from datetime import datetime
        return {'now_hour': datetime.now().hour}

    @app.before_request
    def restore_session_avatar():
        if 'user_id' in session and 'avatar' not in session:
            user = get_db().execute(
                'SELECT avatar FROM users WHERE id = ?', (session['user_id'],)
            ).fetchone()
            if user:
                session['avatar'] = user['avatar']

    @app.before_request
    def track_activity():
        if 'user_id' in session:
            import flask
            
            # Simple activity mapping
            activity_map = {
                'dashboard.index': 'Melihat Beranda',
                'attendance.index': 'Melihat Absensi',
                'schedule.list': 'Melihat Jadwal',
                'profile.view': 'Melihat Profil',
                'members.list': 'Melihat Daftar Anggota'
            }
            
            current_act = activity_map.get(flask.request.endpoint)
            # Activity is only meaningful on these pages. Throttle writes so normal
            # navigation does not turn every request into a synchronous DB commit.
            if current_act:
                db = get_db()
                changed = db.execute('''
                    UPDATE users
                    SET last_active = datetime('now', 'localtime'), current_activity = ?
                    WHERE id = ? AND (
                        current_activity IS NOT ? OR
                        last_active IS NULL OR last_active < datetime('now', '-1 minute')
                    )
                ''', (current_act, session['user_id'], current_act))
                if changed.rowcount:
                    db.commit()

    @app.before_request
    def check_maintenance():
        import flask
        if flask.request.endpoint == 'static':
            return None
        # This setting changes rarely; cache it briefly instead of querying SQLite
        # on every HTML request. Admins still bypass the mode immediately.
        cache = app.extensions['maintenance_mode_cache']
        now = monotonic()
        if now - cache['checked_at'] >= 5:
            mode = get_db().execute(
                'SELECT value FROM system_settings WHERE key = ?', ('maintenance_mode',)
            ).fetchone()
            cache.update(checked_at=now, enabled=bool(mode and mode['value'] == '1'))
        if cache['enabled']:
            db = get_db()
            # Allow admins to bypass maintenance
            if 'user_id' in session:
                user = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
                if user and user['role'] in ['Owner', 'Admin', 'Super Admin', 'Moderator']:
                    return None
            
            # Check if current route is maintenance page, login, or static to avoid loop
            if flask.request.endpoint not in ['dashboard.maintenance', 'auth.admin_login', 'auth.login', 'auth.logout', 'static']:
                return redirect(url_for('dashboard.maintenance'))
        return None

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404

    # Custom Jinja Filters
    @app.template_filter('parse_mentions')
    def parse_mentions(text):
        import re
        from flask import url_for
        # Find @username and replace with link
        return re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', text)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
