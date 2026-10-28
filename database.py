import sqlite3
import os
from flask import g
from werkzeug.security import generate_password_hash
import uuid

DB_PATH = 'paskibra_v2.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA busy_timeout = 10000')
    return db

def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def delete_user_data(db, user_id):
    """Remove a user's private data while preserving shared records and audit history."""
    account = db.execute('SELECT avatar FROM users WHERE id = ?', (user_id,)).fetchone()
    db.execute('UPDATE attendance SET marked_by = NULL WHERE marked_by = ?', (user_id,))
    db.execute('UPDATE announcements SET author_id = NULL WHERE author_id = ?', (user_id,))
    db.execute('UPDATE qr_login_requests SET processed_by = NULL WHERE processed_by = ?', (user_id,))
    db.execute('UPDATE system_logs SET user_id = NULL WHERE user_id = ?', (user_id,))

    if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'messages'").fetchone():
        db.execute('DELETE FROM messages WHERE sender_id = ? OR receiver_id = ?', (user_id, user_id))
    db.execute('DELETE FROM forum_replies WHERE author_id = ? OR topic_id IN (SELECT id FROM forum_topics WHERE author_id = ?)', (user_id, user_id))
    db.execute('DELETE FROM forum_topics WHERE author_id = ?', (user_id,))
    for table in ('attendance', 'activity_logs', 'bugs', 'feature_requests', 'suggestions', 'push_subscriptions', 'notifications'):
        db.execute(f'DELETE FROM {table} WHERE user_id = ?', (user_id,))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chat_messages'").fetchone():
        db.execute('DELETE FROM chat_messages WHERE user_id = ?', (user_id,))
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    if account and account['avatar'] and account['avatar'].startswith('avatar_'):
        avatar_path = os.path.join(os.getcwd(), 'static', 'uploads', os.path.basename(account['avatar']))
        try:
            os.remove(avatar_path)
        except FileNotFoundError:
            pass

def init_db(app):
    with app.app_context():
        db = get_db()
        # WAL lets page reads continue while a short write transaction is active.
        db.execute('PRAGMA journal_mode = WAL')
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())

        # Keep notification links and preference categories available on older databases.
        notification_columns = {
            column[1] for column in db.execute('PRAGMA table_info(notifications)').fetchall()
        }
        if 'url' not in notification_columns:
            db.execute('ALTER TABLE notifications ADD COLUMN url TEXT')
        if 'category' not in notification_columns:
            db.execute("ALTER TABLE notifications ADD COLUMN category TEXT DEFAULT 'general'")
        db.commit()
        
        # Migration: Check if attendance_qr_uuid exists
        cursor = db.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'attendance_qr_uuid' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN attendance_qr_uuid TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_attendance_qr ON users(attendance_qr_uuid)')
            db.commit()

        if 'terms_accepted_at' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN terms_accepted_at TIMESTAMP')
        if 'terms_version' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN terms_version TEXT')
        db.execute("UPDATE system_settings SET value = 'Paskibra' WHERE key = 'app_name' AND value = 'Paskibra Batalion 1'")
        db.commit()

        # Migration: Check if preferences exists
        cursor = db.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'preferences' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN preferences TEXT DEFAULT \'{"dark_mode": false, "compact_mode": false, "sidebar_pins": [], "bottom_nav": ["home", "attendance", "schedule", "profile"]}\'')
            db.commit()

        # Migration: Announcements table improvements
        cursor = db.execute("PRAGMA table_info(announcements)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'category' not in columns:
            db.execute('ALTER TABLE announcements ADD COLUMN category TEXT DEFAULT "Umum"')
        if 'is_pinned' not in columns:
            db.execute('ALTER TABLE announcements ADD COLUMN is_pinned INTEGER DEFAULT 0')
        if 'attachment' not in columns:
            db.execute('ALTER TABLE announcements ADD COLUMN attachment TEXT')
        db.commit()

        # Migration: Schedules table improvements
        cursor = db.execute("PRAGMA table_info(schedules)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'description' not in columns:
            db.execute('ALTER TABLE schedules ADD COLUMN description TEXT')
        if 'status' not in columns:
            db.execute('ALTER TABLE schedules ADD COLUMN status TEXT DEFAULT "Upcoming"') # Upcoming, Completed, Postponed, Cancelled
        if 'is_important' not in columns:
            db.execute('ALTER TABLE schedules ADD COLUMN is_important INTEGER DEFAULT 0')
        db.commit()

        # Migration: Ensure new tables exist
        db.execute('''
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subscription_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                admin_reply TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS forum_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id INTEGER,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                is_pinned INTEGER DEFAULT 0,
                is_closed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (author_id) REFERENCES users (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS forum_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER,
                author_id INTEGER,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (topic_id) REFERENCES forum_topics (id),
                FOREIGN KEY (author_id) REFERENCES users (id)
            )
        ''')
        db.commit()

        # Update existing users who don't have attendance_qr_uuid
        users_without_qr = db.execute('SELECT id FROM users WHERE attendance_qr_uuid IS NULL').fetchall()
        for u in users_without_qr:
            db.execute('UPDATE users SET attendance_qr_uuid = ? WHERE id = ?', (str(uuid.uuid4()), u['id']))
        db.commit()
        
        # Optional first-owner bootstrap. Keep the password out of source control
        # and only create the account when the server operator explicitly sets it.
        owner_password = os.environ.get('PASKIBRA_OWNER_PASSWORD')
        if owner_password:
            owner = db.execute(
                'SELECT id FROM users WHERE username = ? COLLATE NOCASE',
                ('ItsSkellyHer3',)
            ).fetchone()
            pw_hash = generate_password_hash(owner_password)
            if owner:
                db.execute('''
                    UPDATE users SET full_name = ?, class = ?, password = ?, role = 'Owner', status = 'active'
                    WHERE id = ?
                ''', ('ItsSkellyHer3', 'System', pw_hash, owner['id']))
                db.commit()
            else:
                qr_uuid = str(uuid.uuid4())
                att_qr_uuid = str(uuid.uuid4())
                db.execute('''
                    INSERT INTO users (full_name, class, username, password, role, status, qr_code_uuid, attendance_qr_uuid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', ('ItsSkellyHer3', 'System', 'ItsSkellyHer3', pw_hash, 'Owner', 'active', qr_uuid, att_qr_uuid))
                db.commit()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    db = get_db()
    db.execute(query, args)
    db.commit()
