-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    class TEXT NOT NULL,
    username TEXT UNIQUE, 
    password TEXT,
    role TEXT DEFAULT 'member', -- member, admin
    status TEXT DEFAULT 'pending', -- pending, active, suspended
    avatar TEXT DEFAULT 'default_avatar.png',
    bio TEXT,
    qr_code_uuid TEXT UNIQUE,
    attendance_qr_uuid TEXT UNIQUE,
    preferences TEXT DEFAULT '{"dark_mode": false, "compact_mode": false, "sidebar_pins": [], "bottom_nav": ["home", "attendance", "schedule", "profile"]}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- Attendance Table
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'Hadir', -- Hadir, Izin, Sakit, Alpha
    remark TEXT,
    marked_by INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (marked_by) REFERENCES users (id)
);

-- Schedules Table
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    activity TEXT NOT NULL,
    location TEXT DEFAULT 'Lapangan Utama',
    category TEXT DEFAULT 'Latihan',
    priority TEXT DEFAULT 'Normal', -- Low, Normal, High
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Announcements Table
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_id INTEGER,
    is_active INTEGER DEFAULT 1,
    is_banner INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users (id)
);

-- Activity Logs Table
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Bug Reports Table
CREATE TABLE IF NOT EXISTS bugs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'open', -- open, in_progress, resolved, closed
    admin_reply TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Feature Requests Table (Think Hub)
CREATE TABLE IF NOT EXISTS feature_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, planned, implemented, rejected
    votes INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- System Settings
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);

-- QR Login Requests
CREATE TABLE IF NOT EXISTS qr_login_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    class TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, approved, rejected, expired
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP,
    processed_by INTEGER,
    FOREIGN KEY (processed_by) REFERENCES users (id)
);

-- Changelogs
CREATE TABLE IF NOT EXISTS changelogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    category TEXT NOT NULL, -- New, Fix, Improvement
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Suggestions Table
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    content TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, reviewed, resolved
    admin_reply TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Forum Topics Table
CREATE TABLE IF NOT EXISTS forum_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_pinned INTEGER DEFAULT 0,
    is_closed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users (id)
);

-- Forum Replies Table
CREATE TABLE IF NOT EXISTS forum_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER,
    author_id INTEGER,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES forum_topics (id),
    FOREIGN KEY (author_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subscription_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Notifications Table
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, -- Target user, NULL if for all admins
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    type TEXT DEFAULT 'info', -- info, success, warning, alert
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    url TEXT,
    category TEXT DEFAULT 'general',
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- System Logs
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    category TEXT NOT NULL, -- security, user_management, system
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Initial Settings
INSERT OR IGNORE INTO system_settings (key, value, description) VALUES ('maintenance_mode', '0', 'Enable maintenance mode');
INSERT OR IGNORE INTO system_settings (key, value, description) VALUES ('app_name', 'Paskibra', 'Application Name');
INSERT OR IGNORE INTO system_settings (key, value, description) VALUES ('registration_open', '1', 'Allow new registrations');
INSERT OR IGNORE INTO system_settings (key, value, description) VALUES ('registration_closed_reason', 'Pendaftaran anggota sedang ditutup. Silakan coba lagi nanti atau hubungi pengurus untuk informasi lebih lanjut.', 'Pesan yang ditampilkan saat pendaftaran ditutup');
INSERT OR IGNORE INTO system_settings (key, value, description) VALUES ('maintenance_message', 'Kami sedang melakukan pemeliharaan sistem. Silakan coba lagi nanti.', 'Pesan yang ditampilkan saat mode pemeliharaan aktif');

-- Common page lookups and joins.
CREATE INDEX IF NOT EXISTS idx_attendance_user_scan_time ON attendance(user_id, scan_time DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_scan_time ON attendance(scan_time);
CREATE INDEX IF NOT EXISTS idx_attendance_date_user ON attendance(date(scan_time), user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created ON notifications(user_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_forum_replies_topic_created ON forum_replies(topic_id, created_at);
CREATE INDEX IF NOT EXISTS idx_announcements_active_pinned_created ON announcements(is_active, is_pinned DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_schedules_date_time ON schedules(date, time);
