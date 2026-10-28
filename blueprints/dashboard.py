from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from database import get_db
from utils.decorators import login_required
from utils.notifications import notify_user, notify_admins, add_notification
from utils.push import send_push_notification, send_dual_notification

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    db = get_db()
    # Pinned first, then by date
    announcements = db.execute('''
        SELECT a.*, u.full_name as author 
        FROM announcements a 
        JOIN users u ON a.author_id = u.id 
        WHERE a.is_active = 1 
        ORDER BY a.is_pinned DESC, a.created_at DESC 
        LIMIT 5
    ''').fetchall()
    
    schedules = db.execute('SELECT * FROM schedules WHERE date >= DATE("now") ORDER BY date, time LIMIT 3').fetchall()
    
    # Hero banner is the most recent pinned/banner announcement
    banner = db.execute('''
        SELECT * FROM announcements 
        WHERE (is_pinned = 1 OR category = "Pemberitahuan Penting") 
        AND is_active = 1 
        ORDER BY created_at DESC LIMIT 1
    ''').fetchone()
    
    from datetime import datetime
    import locale
    try:
        locale.setlocale(locale.LC_TIME, 'id_ID.UTF-8')
    except:
        pass
    
    today_date = datetime.now().strftime('%A, %d %B %Y')
    
    return render_template('dashboard/index.html', 
                           announcements=announcements, 
                           upcoming_schedules=schedules,
                           banner=banner,
                           today_date=today_date)

@dashboard_bp.route('/announcements')
@login_required
def announcements():
    db = get_db()
    # Sort by pinned, then by created_at
    all_announcements = db.execute('''
        SELECT a.*, u.full_name as author 
        FROM announcements a 
        JOIN users u ON a.author_id = u.id 
        WHERE a.is_active = 1 
        ORDER BY a.is_pinned DESC, a.created_at DESC
    ''').fetchall()
    return render_template('dashboard/announcements.html', announcements=all_announcements)

@dashboard_bp.route('/changelogs')
@login_required
def changelogs():
    db = get_db()
    logs = db.execute('SELECT * FROM changelogs ORDER BY created_at DESC').fetchall()
    return render_template('dashboard/changelogs.html', changelogs=logs)

@dashboard_bp.route('/suggestions', methods=['GET', 'POST'])
@login_required
def suggestions():
    db = get_db()
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            db.execute('INSERT INTO suggestions (user_id, content) VALUES (?, ?)',
                       (session['user_id'], content))
            db.commit()
            
            # Notify Admins
            send_dual_notification(None, 'Saran Baru', f'Seorang anggota mengirimkan saran: "{content[:40]}..."', 'info', url='/admin/suggestions', category='suggestion')
            
            flash('Saran Anda telah dikirim. Terima kasih!', 'success')
        return redirect(url_for('dashboard.suggestions'))
    
    my_suggestions = db.execute('''
        SELECT * FROM suggestions 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    return render_template('dashboard/suggestions.html', suggestions=my_suggestions)

@dashboard_bp.route('/forum')
@login_required
def forum():
    db = get_db()
    topics = db.execute('''
        SELECT t.*, u.full_name as author,
        (SELECT COUNT(*) FROM forum_replies WHERE topic_id = t.id) as reply_count
        FROM forum_topics t
        JOIN users u ON t.author_id = u.id
        ORDER BY t.is_pinned DESC, t.created_at DESC
    ''').fetchall()
    return render_template('dashboard/forum.html', topics=topics)

@dashboard_bp.route('/forum/new', methods=['GET', 'POST'])
@login_required
def new_forum_topic():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        if title and content:
            db = get_db()
            db.execute('INSERT INTO forum_topics (author_id, title, content) VALUES (?, ?, ?)',
                       (session['user_id'], title, content))
            db.commit()
            
            # Notify Admins about new forum topic (optional but good for moderation)
            send_dual_notification(None, 'Topik Forum Baru', f'"{title}" oleh {session.get("full_name")}', 'info', url='/forum', category='forum')
            
            flash('Topik diskusi baru berhasil dibuat!', 'success')
            return redirect(url_for('dashboard.forum'))
    return render_template('dashboard/forum_new.html')

@dashboard_bp.route('/forum/topic/<int:id>', methods=['GET', 'POST'])
@login_required
def forum_topic(id):
    db = get_db()
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            db.execute('INSERT INTO forum_replies (topic_id, author_id, content) VALUES (?, ?, ?)',
                       (id, session['user_id'], content))
            db.commit()
            
            # Notify topic author
            topic = db.execute('SELECT author_id, title FROM forum_topics WHERE id = ?', (id,)).fetchone()
            if topic and topic['author_id'] != session['user_id']:
                send_dual_notification(topic['author_id'], 'Balasan Forum Baru', f'Seseorang membalas topik "{topic["title"][:30]}..."', 'info', url=f'/forum/topic/{id}', category='forum')
                
            flash('Balasan berhasil dikirim.', 'success')
        return redirect(url_for('dashboard.forum_topic', id=id))

    topic = db.execute('''
        SELECT t.*, u.full_name as author, u.role as author_role, u.avatar as author_avatar
        FROM forum_topics t
        JOIN users u ON t.author_id = u.id
        WHERE t.id = ?
    ''', (id,)).fetchone()

    if not topic:
        flash('Topik tidak ditemukan.', 'danger')
        return redirect(url_for('dashboard.forum'))

    replies = db.execute('''
        SELECT r.*, u.full_name as author, u.role as author_role, u.avatar as author_avatar
        FROM forum_replies r
        JOIN users u ON r.author_id = u.id
        WHERE r.topic_id = ?
        ORDER BY r.created_at ASC
    ''', (id,)).fetchall()

    return render_template('dashboard/forum_view.html', topic=topic, replies=replies)

@dashboard_bp.route('/forum/topic/<int:id>/delete', methods=['POST'])
@login_required
def delete_own_forum_topic(id):
    db = get_db()
    topic = db.execute('SELECT author_id FROM forum_topics WHERE id = ?', (id,)).fetchone()
    is_admin = session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']
    if not topic:
        flash('Topik tidak ditemukan.', 'danger')
    elif topic['author_id'] != session['user_id'] and not is_admin:
        flash('Anda hanya dapat menghapus topik milik sendiri.', 'danger')
        return redirect(url_for('dashboard.forum_topic', id=id))
    else:
        db.execute('DELETE FROM forum_replies WHERE topic_id = ?', (id,))
        db.execute('DELETE FROM forum_topics WHERE id = ?', (id,))
        db.commit()
        flash('Topik diskusi dan seluruh balasannya telah dihapus.', 'success')
    return redirect(url_for('dashboard.forum'))

@dashboard_bp.route('/report-bug', methods=['GET', 'POST'])
@login_required
def report_bug():
    db = get_db()
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category', 'UI/UX')
        
        db.execute('INSERT INTO bugs (user_id, title, description, status) VALUES (?, ?, ?, ?)',
                   (session['user_id'], title, description, 'open'))
        db.commit()
        
        # Notify Admins
        send_dual_notification(None, 'Bug Report Baru', f'Bug baru dilaporkan: "{title}"', 'alert', url='/admin/bugs', category='bug')
        
        flash('Bug reported successfully! Thank you for your feedback.', 'success')
        return redirect(url_for('dashboard.report_bug'))
    
    # Fetch previous reports by this user
    my_reports = db.execute('''
        SELECT * FROM bugs 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    return render_template('dashboard/report_bug.html', reports=my_reports)

@dashboard_bp.route('/think', methods=['GET', 'POST'])
@login_required
def think():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        db = get_db()
        db.execute('INSERT INTO feature_requests (user_id, title, description) VALUES (?, ?, ?)',
                   (session['user_id'], title, description))
        db.commit()
        flash('Idea submitted to Think Hub!', 'success')
        return redirect(url_for('dashboard.index'))
    
    db = get_db()
    ideas = db.execute('SELECT f.*, u.full_name FROM feature_requests f JOIN users u ON f.user_id = u.id ORDER BY created_at DESC').fetchall()
    return render_template('dashboard/think.html', ideas=ideas)

@dashboard_bp.route('/credits')
@login_required
def credits():
    return render_template('dashboard/credits.html')

@dashboard_bp.route('/maintenance')
def maintenance():
    db = get_db()
    mode = db.execute('SELECT value FROM system_settings WHERE key = "maintenance_mode"').fetchone()
    if not mode or mode['value'] == '0':
        return redirect(url_for('dashboard.index'))
    setting = db.execute(
        'SELECT value FROM system_settings WHERE key = ?', ('maintenance_message',)
    ).fetchone()
    message = (setting['value'] if setting else '').strip()
    return render_template(
        'maintenance.html',
        maintenance_message=message or 'Kami sedang melakukan pemeliharaan sistem. Silakan coba lagi nanti.'
    )
