from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from database import get_db, delete_user_data
from utils.decorators import admin_required, super_admin_required
from utils.notifications import notify_user, notify_admins, add_notification
from utils.push import send_push_notification, send_dual_notification, broadcast_push_notification
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import uuid
import os
from datetime import date, datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@admin_required
def dashboard():
    db = get_db()
    stats = {
        'total_users': db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'pending_users': db.execute('SELECT COUNT(*) FROM users WHERE status = "pending"').fetchone()[0],
        'active_users': db.execute('SELECT COUNT(*) FROM users WHERE status = "active"').fetchone()[0],
        'today_attendance': db.execute('SELECT COUNT(*) FROM attendance WHERE DATE(scan_time) = DATE("now")').fetchone()[0],
        'open_bugs': db.execute('SELECT COUNT(*) FROM bugs WHERE status = "open"').fetchone()[0],
        'pending_suggestions': db.execute('SELECT COUNT(*) FROM suggestions WHERE status = "pending"').fetchone()[0],
        'active_forum_topics': db.execute('SELECT COUNT(*) FROM forum_topics WHERE is_closed = 0').fetchone()[0]
    }
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/admins')
@admin_required
def admin_list():
    db = get_db()
    admins = db.execute('''
        SELECT * FROM users 
        WHERE role IN ('Owner', 'Admin', 'Super Admin', 'Moderator') 
        ORDER BY role DESC, full_name ASC
    ''').fetchall()
    return render_template('admin/admins.html', admins=admins)

@admin_bp.route('/admins/add', methods=['GET', 'POST'])
@super_admin_required
def add_admin():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        passkey = request.form.get('passkey')
        allowed_roles = {'Admin', 'Super Admin', 'Moderator'}
        if session.get('role') == 'Owner':
            allowed_roles.add('Owner')
        if role not in allowed_roles:
            flash('Role administrator tidak valid.', 'danger')
            return redirect(url_for('admin.add_admin'))
        
        if passkey != 'skelly2026':
            flash('Invalid Admin Passkey!', 'danger')
            return redirect(url_for('admin.add_admin'))
        
        db = get_db()
        # Check if username exists
        existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            flash('Username already exists!', 'danger')
            return redirect(url_for('admin.add_admin'))
        
        pw_hash = generate_password_hash(password)
        qr_uuid = str(uuid.uuid4())
        att_qr_uuid = str(uuid.uuid4())
        
        db.execute('''
            INSERT INTO users (full_name, username, password, role, status, qr_code_uuid, attendance_qr_uuid, class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (full_name, username, pw_hash, role, 'active', qr_uuid, att_qr_uuid, 'System'))
        db.commit()
        
        flash(f'Admin {full_name} created successfully!', 'success')
        return redirect(url_for('admin.admin_list'))
        
    return render_template('admin/admin_form.html', action='Add', admin=None)

@admin_bp.route('/admins/edit/<int:id>', methods=['GET', 'POST'])
@super_admin_required
def edit_admin(id):
    db = get_db()
    admin_data = db.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
    
    if not admin_data:
        flash('Admin not found!', 'danger')
        return redirect(url_for('admin.admin_list'))

    if admin_data['role'] == 'Owner' and session.get('role') != 'Owner':
        flash('Hanya Owner yang dapat mengubah akun Owner.', 'danger')
        return redirect(url_for('admin.admin_list'))
        
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        role = request.form.get('role')
        status = request.form.get('status')
        password = request.form.get('password')
        allowed_roles = {'Admin', 'Super Admin', 'Moderator'}
        if session.get('role') == 'Owner':
            allowed_roles.add('Owner')
        if role not in allowed_roles:
            flash('Role administrator tidak valid.', 'danger')
            return redirect(url_for('admin.edit_admin', id=id))
        
        if password:
            pw_hash = generate_password_hash(password)
            db.execute('UPDATE users SET full_name = ?, role = ?, status = ?, password = ? WHERE id = ?',
                       (full_name, role, status, pw_hash, id))
        else:
            db.execute('UPDATE users SET full_name = ?, role = ?, status = ? WHERE id = ?',
                       (full_name, role, status, id))
        db.commit()
        
        flash('Admin updated successfully!', 'success')
        return redirect(url_for('admin.admin_list'))
        
    return render_template('admin/admin_form.html', action='Edit', admin=admin_data)

@admin_bp.route('/users')
@admin_required
def users():
    db = get_db()
    # Fetch users with their attendance summary
    all_users = db.execute('''
        SELECT u.*, 
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Hadir") as hadir,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Izin") as izin,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Sakit") as sakit,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Alpha") as alpha
        FROM users u 
        ORDER BY u.full_name ASC
    ''').fetchall()
    
    # Get unique classes and roles for filters
    classes = db.execute('SELECT DISTINCT class FROM users WHERE class IS NOT NULL AND class != "" ORDER BY class ASC').fetchall()
    roles = db.execute('SELECT DISTINCT role FROM users WHERE role IS NOT NULL AND role != "" ORDER BY role ASC').fetchall()
    
    return render_template('admin/users.html', 
                           users=all_users, 
                           classes=[c['class'] for c in classes],
                           roles=[r['role'] for r in roles])

@admin_bp.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        m_class = request.form.get('class')
        role = request.form.get('role', 'member')
        
        db = get_db()
        qr_uuid = str(uuid.uuid4())
        att_qr_uuid = str(uuid.uuid4())
        
        db.execute('''
            INSERT INTO users (full_name, class, role, status, qr_code_uuid, attendance_qr_uuid)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (full_name, m_class, role, 'active', qr_uuid, att_qr_uuid))
        db.commit()
        
        flash(f'Anggota {full_name} berhasil ditambahkan secara manual!', 'success')
        return redirect(url_for('admin.users'))
        
    return render_template('admin/user_form.html', user=None)

@admin_bp.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    db = get_db()
    user_data = db.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
    
    if not user_data:
        flash('User tidak ditemukan!', 'danger')
        return redirect(url_for('admin.users'))

    if user_data['role'] == 'Owner' and session.get('role') != 'Owner':
        flash('Akun Owner hanya dapat dikelola oleh Owner.', 'danger')
        return redirect(url_for('admin.users'))
        
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        m_class = request.form.get('class')
        role = request.form.get('role')
        status = request.form.get('status')
        bio = request.form.get('bio')
        if user_data['role'] == 'Owner' and role != 'Owner':
            flash('Role Owner hanya dapat diubah melalui manajemen administrator.', 'danger')
            return redirect(url_for('admin.users'))
        
        db.execute('''
            UPDATE users 
            SET full_name = ?, class = ?, role = ?, status = ?, bio = ? 
            WHERE id = ?
        ''', (full_name, m_class, role, status, bio, id))
        db.commit()
        
        flash(f'Data {full_name} berhasil diperbarui!', 'success')
        return redirect(url_for('admin.users'))
        
    return render_template('admin/user_form.html', user=user_data)

@admin_bp.route('/users/reset-login/<int:id>', methods=['POST'])
@admin_required
def reset_user_login(id):
    db = get_db()
    target = db.execute('SELECT role FROM users WHERE id = ?', (id,)).fetchone()
    actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if target and target['role'] == 'Owner' and (not actor or actor['role'] != 'Owner'):
        flash('Akun Owner hanya dapat dikelola oleh Owner.', 'danger')
        return redirect(url_for('admin.users'))
    # Clear password and username to force re-registration or just reset password?
    # User said "reset login access", usually it means clearing password.
    # We will clear password so they can set a new one, or just set a default one.
    # For this app, maybe they need to scan QR again? 
    # Let's just clear password and username to allow them to "Register" again with their QR.
    db.execute('UPDATE users SET username = NULL, password = NULL WHERE id = ?', (id,))
    db.commit()
    flash('Akses login pengguna telah direset. Pengguna harus mendaftar ulang menggunakan QR mereka.', 'warning')
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/regenerate-qr/<int:id>', methods=['POST'])
@admin_required
def regenerate_user_qr(id):
    db = get_db()
    target = db.execute('SELECT role FROM users WHERE id = ?', (id,)).fetchone()
    actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if target and target['role'] == 'Owner' and (not actor or actor['role'] != 'Owner'):
        flash('Akun Owner hanya dapat dikelola oleh Owner.', 'danger')
        return redirect(url_for('admin.users'))
    new_qr = str(uuid.uuid4())
    new_att_qr = str(uuid.uuid4())
    db.execute('UPDATE users SET qr_code_uuid = ?, attendance_qr_uuid = ? WHERE id = ?', 
               (new_qr, new_att_qr, id))
    db.commit()
    flash('QR Code berhasil diregenerasi!', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/bulk-action', methods=['POST'])
@admin_required
def bulk_action():
    user_ids = request.form.getlist('user_ids')
    action = request.form.get('action')
    
    if not user_ids:
        flash('Pilih setidaknya satu anggota!', 'warning')
        return redirect(url_for('admin.users'))
        
    db = get_db()
    if action == 'delete':
        actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        actor_role = actor['role'] if actor else ''
        deleted = 0
        skipped_admins = 0
        for raw_id in user_ids:
            try:
                target_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            target = db.execute('SELECT role FROM users WHERE id = ?', (target_id,)).fetchone()
            if target_id == session['user_id']:
                continue
            if target and target['role'] == 'Owner' and actor_role != 'Owner':
                skipped_admins += 1
                continue
            if target and target['role'] in ['Admin', 'Super Admin', 'Moderator'] and actor_role not in ['Super Admin', 'Owner']:
                skipped_admins += 1
                continue
            if target:
                delete_user_data(db, target_id)
                deleted += 1
        db.commit()
        message = f'{deleted} akun berhasil dihapus.'
        if skipped_admins:
            message += f' {skipped_admins} akun administrator hanya dapat dihapus oleh Owner atau Super Admin.'
        flash(message, 'success' if deleted else 'warning')
    
    elif action == 'activate':
        actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        allowed_ids = []
        for raw_id in user_ids:
            try:
                target_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            target = db.execute('SELECT role FROM users WHERE id = ?', (target_id,)).fetchone()
            if target and (target['role'] != 'Owner' or (actor and actor['role'] == 'Owner')):
                allowed_ids.append(target_id)
        if allowed_ids:
            placeholders = ', '.join(['?'] * len(allowed_ids))
            db.execute(f'UPDATE users SET status = "active" WHERE id IN ({placeholders})', allowed_ids)
        db.commit()
        flash(f'{len(allowed_ids)} anggota berhasil diaktifkan.', 'success' if allowed_ids else 'warning')
        
    elif action == 'suspend':
        if str(session['user_id']) in user_ids:
            flash('Anda tidak dapat menonaktifkan akun Anda sendiri!', 'danger')
            return redirect(url_for('admin.users'))
        actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        allowed_ids = []
        for raw_id in user_ids:
            try:
                target_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            target = db.execute('SELECT role FROM users WHERE id = ?', (target_id,)).fetchone()
            if target and (target['role'] != 'Owner' or (actor and actor['role'] == 'Owner')):
                allowed_ids.append(target_id)
        if allowed_ids:
            placeholders = ', '.join(['?'] * len(allowed_ids))
            db.execute(f'UPDATE users SET status = "suspended" WHERE id IN ({placeholders})', allowed_ids)
        db.commit()
        flash(f'{len(allowed_ids)} anggota berhasil ditangguhkan.', 'success' if allowed_ids else 'warning')

    return redirect(url_for('admin.users'))

@admin_bp.route('/users/export')
@admin_required
def export_users():
    import csv
    import io
    from flask import Response
    
    db = get_db()
    users = db.execute('''
        SELECT u.*, 
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Hadir") as hadir,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Izin") as izin,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Sakit") as sakit,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Alpha") as alpha
        FROM users u 
        ORDER BY u.full_name ASC
    ''').fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['ID', 'Nama Lengkap', 'Kelas', 'Username', 'Role', 'Status', 'Hadir', 'Izin', 'Sakit', 'Alpha', 'Terdaftar'])
    
    for u in users:
        writer.writerow([
            u['id'], u['full_name'], u['class'], u['username'], u['role'], u['status'],
            u['hadir'], u['izin'], u['sakit'], u['alpha'], u['created_at']
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=daftar_anggota_paskibra.csv"}
    )

@admin_bp.route('/pending')
@admin_required
def pending():
    db = get_db()
    pending_users = db.execute('SELECT * FROM users WHERE status = "pending" ORDER BY full_name ASC').fetchall()
    return render_template('admin/pending.html', users=pending_users)

@admin_bp.route('/approve/<int:user_id>', methods=['POST'])
@admin_required
def approve_user(user_id):
    db = get_db()
    target = db.execute('SELECT id, full_name, status FROM users WHERE id = ?', (user_id,)).fetchone()
    if not target or target['status'] != 'pending':
        flash('Pendaftaran ini sudah diproses atau tidak ditemukan.', 'warning')
        return redirect(url_for('admin.pending'))
    db.execute('UPDATE users SET status = "active" WHERE id = ?', (user_id,))
    db.commit()
    
    send_dual_notification(user_id, 'Akun Disetujui', 'Selamat! Akun Anda telah disetujui oleh admin. Anda sekarang dapat mengakses portal.', 'success', url='/', category='approval')
    
    flash(f'Akun {target["full_name"]} disetujui.', 'success')
    return redirect(url_for('admin.pending'))

@admin_bp.route('/reject/<int:user_id>', methods=['POST'])
@admin_required
def reject_user(user_id):
    db = get_db()
    target = db.execute('SELECT id, full_name, status FROM users WHERE id = ?', (user_id,)).fetchone()
    if not target or target['status'] != 'pending':
        flash('Pendaftaran ini sudah diproses atau tidak ditemukan.', 'warning')
        return redirect(url_for('admin.pending'))
    db.execute('UPDATE users SET status = "rejected" WHERE id = ?', (user_id,))
    db.commit()
    send_dual_notification(user_id, 'Pendaftaran Ditolak', 'Mohon maaf, pendaftaran Anda belum dapat kami setujui saat ini.', 'alert', category='approval')
    flash(f'Pendaftaran {target["full_name"]} ditolak.', 'success')
    return redirect(url_for('admin.pending'))

@admin_bp.route('/attendance')
@admin_required
def attendance():
    db = get_db()
    today = date.today()
    default_start = today - timedelta(days=29)
    raw_start = request.args.get('from', '')
    raw_end = request.args.get('to', '')
    try:
        date_from = datetime.strptime(raw_start, '%Y-%m-%d').date() if raw_start else default_start
    except ValueError:
        date_from = default_start
    try:
        date_to = datetime.strptime(raw_end, '%Y-%m-%d').date() if raw_end else today
    except ValueError:
        date_to = today
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    selected_status = request.args.get('status', '')
    if selected_status not in {'Hadir', 'Izin', 'Sakit', 'Alpha'}:
        selected_status = ''

    active_members = db.execute('SELECT COUNT(*) FROM users WHERE status = "active"').fetchone()[0]
    today_rows = db.execute('''
        WITH ranked AS (
            SELECT a.user_id, a.status,
                   ROW_NUMBER() OVER (PARTITION BY a.user_id ORDER BY a.scan_time DESC, a.id DESC) AS row_num
            FROM attendance a
            JOIN users u ON u.id = a.user_id AND u.status = 'active'
            WHERE date(a.scan_time, 'localtime') = date('now', 'localtime')
        )
        SELECT status, COUNT(*) AS total FROM ranked WHERE row_num = 1 GROUP BY status
    ''').fetchall()
    today_counts = {row['status']: row['total'] for row in today_rows}
    for status_name in ('Hadir', 'Izin', 'Sakit', 'Alpha'):
        today_counts.setdefault(status_name, 0)
    today_counts['belum'] = max(0, active_members - sum(today_counts.values()))
    attendance_rate = round((active_members - today_counts['belum']) * 100 / active_members) if active_members else 0
    present_rate = round(today_counts['Hadir'] * 100 / active_members) if active_members else 0

    daily_rows = db.execute('''
        SELECT date(scan_time, 'localtime') AS day, COUNT(DISTINCT user_id) AS total
        FROM attendance
        WHERE date(scan_time, 'localtime') >= date('now', 'localtime', '-13 days')
          AND date(scan_time, 'localtime') <= date('now', 'localtime')
        GROUP BY date(scan_time, 'localtime')
    ''').fetchall()
    daily_totals = {row['day']: row['total'] for row in daily_rows}
    trend = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        trend.append({'label': day.strftime('%d %b'), 'date': day.isoformat(), 'total': daily_totals.get(day.isoformat(), 0)})
    trend_max = max((item['total'] for item in trend), default=0)
    trend_sum = sum(item['total'] for item in trend)

    filters = ["date(a.scan_time, 'localtime') BETWEEN ? AND ?"]
    params = [date_from.isoformat(), date_to.isoformat()]
    if selected_status:
        filters.append('a.status = ?')
        params.append(selected_status)
    where_sql = ' AND '.join(filters)
    history = db.execute('''
        SELECT a.*, u.full_name, u.class, u.username
        FROM attendance a 
        JOIN users u ON a.user_id = u.id 
        WHERE ''' + where_sql + '''
        ORDER BY a.scan_time DESC
        LIMIT 250
    ''', params).fetchall()
    period_total = db.execute('SELECT COUNT(*) FROM attendance a WHERE ' + where_sql, params).fetchone()[0]
    return render_template(
        'admin/attendance.html', history=history, today_counts=today_counts,
        active_members=active_members, trend=trend, trend_max=trend_max or 1,
        trend_sum=trend_sum, period_total=period_total,
        attendance_rate=attendance_rate,
        present_rate=present_rate,
        date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        selected_status=selected_status
    )

@admin_bp.route('/announcements', methods=['GET', 'POST'])
@admin_required
def announcements():
    db = get_db()
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        category = request.form.get('category', 'Umum')
        is_pinned = 1 if request.form.get('is_pinned') else 0
        
        attachment_path = None
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename:
                filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
                upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'announcements')
                if not os.path.exists(upload_path):
                    os.makedirs(upload_path)
                file.save(os.path.join(upload_path, filename))
                attachment_path = f"announcements/{filename}"

        db.execute('''
            INSERT INTO announcements (title, content, author_id, category, is_pinned, attachment) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, content, session['user_id'], category, is_pinned, attachment_path))
        db.commit()
        
        # Broadcast to all users
        add_notification(None, 'Pengumuman Baru', title, 'info', url='/announcements', category='announcement')
        broadcast_push_notification('Pengumuman Baru', title, url='/announcements', category='announcement')
        
        flash('Pengumuman berhasil diterbitkan!', 'success')
        return redirect(url_for('admin.announcements'))
        
    all_ann_rows = db.execute('''
        SELECT a.*, u.full_name as author_name 
        FROM announcements a 
        LEFT JOIN users u ON a.author_id = u.id 
        ORDER BY a.is_pinned DESC, a.created_at DESC
    ''').fetchall()
    
    all_ann = [dict(row) for row in all_ann_rows]
    return render_template('admin/announcements.html', announcements=all_ann)

@admin_bp.route('/announcements/edit/<int:id>', methods=['POST'])
@admin_required
def edit_announcement(id):
    db = get_db()
    title = request.form.get('title')
    content = request.form.get('content')
    category = request.form.get('category')
    is_pinned = 1 if request.form.get('is_pinned') else 0
    
    db.execute('''
        UPDATE announcements 
        SET title = ?, content = ?, category = ?, is_pinned = ? 
        WHERE id = ?
    ''', (title, content, category, is_pinned, id))
    db.commit()
    flash('Pengumuman berhasil diperbarui.', 'success')
    return redirect(url_for('admin.announcements'))

@admin_bp.route('/announcements/toggle-pin/<int:id>')
@admin_required
def toggle_pin_announcement(id):
    db = get_db()
    db.execute('UPDATE announcements SET is_pinned = 1 - is_pinned WHERE id = ?', (id,))
    db.commit()
    flash('Status pin pengumuman diperbarui.', 'success')
    return redirect(url_for('admin.announcements'))

@admin_bp.route('/qr-scanner')
@admin_required
def qr_scanner():
    return render_template('admin/qr_scanner.html')

@admin_bp.route('/scan-qr', methods=['POST'])
@admin_required
def scan_qr():
    qr_uuid = request.json.get('qr_uuid')
    db = get_db()
    
    # Strictly Identity/Login QR ONLY
    user = db.execute('SELECT * FROM users WHERE qr_code_uuid = ?', (qr_uuid,)).fetchone()
    
    if not user:
        # Check if they accidentally scanned the attendance QR
        is_att = db.execute('SELECT 1 FROM users WHERE attendance_qr_uuid = ?', (qr_uuid,)).fetchone()
        if is_att:
            return {'status': 'error', 'message': 'Ini adalah QR Presensi. Gunakan Scanner di Menu Absensi untuk absensi.'}
        return {'status': 'error', 'message': 'QR Identitas tidak valid atau tidak terdaftar.'}

    if user['status'] == 'pending':
        return {
            'status': 'pending_approval',
            'message': f'Aktivasi Akun: {user["full_name"]}',
            'user': {
                'id': user['id'],
                'full_name': user['full_name'],
                'class': user['class'],
                'username': user['username'],
                'role': user['role'],
                'status': user['status']
            }
        }

    return {
        'status': 'info', 
        'message': f'Identitas Terverifikasi: {user["full_name"]} ({user["role"]})',
        'user': dict(user)
    }

@admin_bp.route('/process-approval', methods=['POST'])
@admin_required
def process_approval():
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return {'status': 'error', 'message': 'Akun tidak valid.'}, 400
    action = data.get('action') # approve, reject
    if action not in {'approve', 'reject'}:
        return {'status': 'error', 'message': 'Aksi tidak valid.'}, 400
    
    db = get_db()
    target = db.execute('SELECT id, full_name, status FROM users WHERE id = ?', (user_id,)).fetchone()
    if not target or target['status'] != 'pending':
        return {'status': 'error', 'message': 'Pendaftaran sudah diproses atau tidak ditemukan.'}, 404
    if action == 'approve':
        db.execute('UPDATE users SET status = "active" WHERE id = ?', (user_id,))
        db.commit()
        send_dual_notification(user_id, 'Akun Disetujui', 'Pendaftaran Anda telah disetujui. Selamat datang!', 'success', url='/', category='approval')
        return {'status': 'success', 'message': 'Akun berhasil disetujui dan diaktifkan.'}
    elif action == 'reject':
        db.execute('UPDATE users SET status = "rejected" WHERE id = ?', (user_id,))
        db.commit()
        send_dual_notification(user_id, 'Pendaftaran Ditolak', 'Mohon maaf, pendaftaran Anda belum dapat kami setujui saat ini.', 'alert', category='approval')
        return {'status': 'success', 'message': 'Pendaftaran akun telah ditolak.'}
    
    return {'status': 'error', 'message': 'Aksi tidak valid.'}

@admin_bp.route('/broadcast', methods=['POST'])
@admin_required
def broadcast():
    title = request.form.get('title')
    message = request.form.get('message')
    target = request.form.get('target', 'all')
    
    db = get_db()
    if target == 'all':
        # Notification to all active members
        # add_notification with user_id=None represents "global" in my system logic if handled right
        # But actually for individual read state, it's better to add for each or use a global flag.
        # My current system uses user_id=None for "admins". 
        # For "all members", it's better to loop or have a specific logic.
        # Given the "all" requirement, I'll use a specific broadcast logic.
        
        users = db.execute('SELECT id FROM users WHERE status = "active"').fetchall()
        for u in users:
            add_notification(u['id'], title, message, 'info', category='announcement')
        
        broadcast_push_notification(title, message, category='announcement')
        flash(f'Broadcast sent to {len(users)} members!', 'success')
        
    elif target == 'admin':
        notify_admins(title, message, 'warning', category='general')
        flash('Broadcast sent to all administrators.', 'success')
        
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    db = get_db()
    if request.method == 'POST':
        # Only update known setting keys and normalize the two feature switches.
        known_keys = {
            row['key'] for row in db.execute('SELECT key FROM system_settings').fetchall()
        }
        values = {
            key: value for key, value in request.form.items()
            if key in known_keys
        }
        for key in ('maintenance_mode', 'registration_open'):
            if key in known_keys:
                values[key] = '1' if request.form.get(key) == '1' else '0'
        if 'registration_closed_reason' in known_keys:
            values['registration_closed_reason'] = (
                request.form.get('registration_closed_reason', '').strip()[:500]
            )
        if 'maintenance_message' in known_keys:
            values['maintenance_message'] = (
                request.form.get('maintenance_message', '').strip()[:1000]
            )
        for key, value in values.items():
            db.execute('UPDATE system_settings SET value = ? WHERE key = ?', (value, key))
        db.commit()
        flash('Pengaturan aplikasi berhasil disimpan.', 'success')
        return redirect(url_for('admin.settings'))
        
    all_settings = db.execute('SELECT * FROM system_settings').fetchall()
    return render_template('admin/settings.html', settings=all_settings)

@admin_bp.route('/bugs')
@admin_required
def bugs():
    db = get_db()
    all_bugs = db.execute('''
        SELECT b.*, u.full_name as reporter_name 
        FROM bugs b 
        JOIN users u ON b.user_id = u.id 
        ORDER BY b.created_at DESC
    ''').fetchall()
    return render_template('admin/bugs.html', bugs=all_bugs)

@admin_bp.route('/bugs/resolve/<int:id>', methods=['POST'])
@admin_required
def resolve_bug(id):
    db = get_db()
    bug = db.execute('SELECT user_id, title FROM bugs WHERE id = ?', (id,)).fetchone()
    db.execute('UPDATE bugs SET status = "Resolved" WHERE id = ?', (id,))
    db.commit()
    
    if bug:
        send_dual_notification(bug['user_id'], 'Laporan Bug Selesai', f'Bug "{bug["title"]}" telah diperbaiki.', 'success', url='/report-bug', category='bug')
        
    flash('Bug marked as resolved!', 'success')
    return redirect(url_for('admin.bugs'))

@admin_bp.route('/bugs/delete/<int:id>', methods=['POST'])
@admin_required
def delete_bug(id):
    db = get_db()
    db.execute('DELETE FROM bugs WHERE id = ?', (id,))
    db.commit()
    flash('Laporan kendala telah dihapus.', 'success')
    return redirect(url_for('admin.bugs'))

@admin_bp.route('/suggestions')
@admin_required
def suggestions():
    db = get_db()
    all_suggestions = db.execute('''
        SELECT s.*, u.full_name as author
        FROM suggestions s
        JOIN users u ON s.user_id = u.id
        ORDER BY s.created_at DESC
    ''').fetchall()
    return render_template('admin/suggestions.html', suggestions=all_suggestions)

@admin_bp.route('/suggestions/reply/<int:id>', methods=['POST'])
@admin_required
def reply_suggestion(id):
    db = get_db()
    reply = request.form.get('admin_reply')
    status = request.form.get('status', 'reviewed')
    
    # Get user_id of the suggestion author
    sugg = db.execute('SELECT user_id, content FROM suggestions WHERE id = ?', (id,)).fetchone()
    
    db.execute('UPDATE suggestions SET admin_reply = ?, status = ? WHERE id = ?',
               (reply, status, id))
    db.commit()
    
    if sugg:
        send_dual_notification(sugg['user_id'], 'Saran Anda Ditanggapi', f'Admin telah menanggapi saran Anda: "{sugg["content"][:30]}..."', 'success', url='/suggestions', category='suggestion')
        
    flash('Tanggapan saran berhasil dikirim.', 'success')
    return redirect(url_for('admin.suggestions'))

@admin_bp.route('/suggestions/delete/<int:id>', methods=['POST'])
@admin_required
def delete_suggestion(id):
    db = get_db()
    db.execute('DELETE FROM suggestions WHERE id = ?', (id,))
    db.commit()
    flash('Saran berhasil dihapus.', 'success')
    return redirect(url_for('admin.suggestions'))

@admin_bp.route('/forum')
@admin_required
def manage_forum():
    db = get_db()
    topics = db.execute('''
        SELECT t.*, u.full_name as author
        FROM forum_topics t
        JOIN users u ON t.author_id = u.id
        ORDER BY t.created_at DESC
    ''').fetchall()
    return render_template('admin/forum.html', topics=topics)

@admin_bp.route('/forum/topic/delete/<int:id>', methods=['POST'])
@admin_required
def delete_forum_topic(id):
    db = get_db()
    db.execute('DELETE FROM forum_topics WHERE id = ?', (id,))
    db.execute('DELETE FROM forum_replies WHERE topic_id = ?', (id,))
    db.commit()
    flash('Topik diskusi dan semua balasannya telah dihapus.', 'success')
    return redirect(url_for('admin.manage_forum'))

@admin_bp.route('/forum/topic/toggle-pin/<int:id>')
@admin_required
def toggle_forum_pin(id):
    db = get_db()
    db.execute('UPDATE forum_topics SET is_pinned = 1 - is_pinned WHERE id = ?', (id,))
    db.commit()
    return redirect(url_for('admin.manage_forum'))

@admin_bp.route('/forum/topic/toggle-close/<int:id>')
@admin_required
def toggle_forum_close(id):
    db = get_db()
    db.execute('UPDATE forum_topics SET is_closed = 1 - is_closed WHERE id = ?', (id,))
    db.commit()
    return redirect(url_for('admin.manage_forum'))

@admin_bp.route('/feature-requests')
@admin_required
def feature_requests():
    db = get_db()
    all_features = db.execute('''
        SELECT f.*, u.full_name as requester_name 
        FROM feature_requests f 
        JOIN users u ON f.user_id = u.id 
        ORDER BY f.votes DESC, f.created_at DESC
    ''').fetchall()
    return render_template('admin/feature_requests.html', features=all_features)

@admin_bp.route('/feature-requests/implement/<int:id>', methods=['POST'])
@admin_required
def implement_feature(id):
    db = get_db()
    db.execute('UPDATE feature_requests SET status = "implemented" WHERE id = ?', (id,))
    db.commit()
    flash('Feature marked as implemented!', 'success')
    return redirect(url_for('admin.feature_requests'))

@admin_bp.route('/announcements/delete/<int:id>', methods=['POST'])
@admin_required
def delete_announcement(id):
    db = get_db()
    db.execute('DELETE FROM announcements WHERE id = ?', (id,))
    db.commit()
    flash('Announcement deleted!', 'success')
    return redirect(url_for('admin.announcements'))

@admin_bp.route('/changelogs', methods=['GET', 'POST'])
@admin_required
def changelogs():
    db = get_db()
    if request.method == 'POST':
        version = request.form.get('version', '').strip()
        category = request.form.get('category', '').strip()
        content = request.form.get('content', '').strip()
        if not version or category not in {'New', 'Fix', 'Improvement'} or not content:
            flash('Isi versi, kategori, dan catatan pembaruan dengan benar.', 'danger')
        else:
            db.execute('INSERT INTO changelogs (version, category, content) VALUES (?, ?, ?)', (version, category, content))
            db.commit()
            flash('Catatan pembaruan berhasil diterbitkan.', 'success')
        return redirect(url_for('admin.changelogs'))
    logs = db.execute('SELECT * FROM changelogs ORDER BY created_at DESC').fetchall()
    return render_template('admin/changelogs.html', changelogs=logs)

@admin_bp.route('/changelogs/delete/<int:id>', methods=['POST'])
@admin_required
def delete_changelog(id):
    db = get_db()
    db.execute('DELETE FROM changelogs WHERE id = ?', (id,))
    db.commit()
    flash('Catatan pembaruan dihapus.', 'success')
    return redirect(url_for('admin.changelogs'))

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    db = get_db()
    # Check if user is trying to delete themselves or a super admin
    target = db.execute('SELECT role, full_name FROM users WHERE id = ?', (user_id,)).fetchone()
    if user_id == session['user_id']:
        flash('Anda tidak dapat menghapus akun sendiri.', 'danger')
        return redirect(url_for('admin.users'))

    if not target:
        flash('Akun tidak ditemukan.', 'warning')
        return redirect(url_for('admin.users'))

    actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    actor_role = actor['role'] if actor else ''
    if target['role'] == 'Owner' and actor_role != 'Owner':
        flash('Hanya Owner yang dapat menghapus akun Owner.', 'danger')
        return redirect(url_for('admin.users'))
    if target['role'] in ['Admin', 'Super Admin', 'Moderator'] and actor_role not in ['Super Admin', 'Owner']:
        flash('Hanya Owner atau Super Admin yang dapat menghapus akun administrator.', 'danger')
        return redirect(url_for('admin.users'))
        
    delete_user_data(db, user_id)
    db.commit()
    flash(f'Akun {target["full_name"]} dan data terkait berhasil dihapus.', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/status/<int:user_id>/<string:status>', methods=['POST'])
@admin_required
def update_user_status(user_id, status):
    db = get_db()
    if user_id == session['user_id']:
        flash('You cannot change your own status!', 'danger')
        return redirect(url_for('admin.users'))
        
    target = db.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()
    actor = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if target and target['role'] == 'Owner' and (not actor or actor['role'] != 'Owner'):
        flash('Akun Owner hanya dapat dikelola oleh Owner.', 'danger')
        return redirect(url_for('admin.users'))
    if status not in {'active', 'suspended', 'pending'}:
        flash('Status akun tidak valid.', 'danger')
        return redirect(url_for('admin.users'))
    db.execute('UPDATE users SET status = ? WHERE id = ?', (status, user_id))
    db.commit()
    flash(f'User status updated to {status}.', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/attendance/mark/<int:user_id>/<string:status>', methods=['POST'])
@admin_required
def mark_attendance(user_id, status):
    if status not in {'Hadir', 'Izin', 'Sakit', 'Alpha'}:
        flash('Status presensi tidak valid.', 'danger')
        return redirect(request.referrer or url_for('admin.users'))
    db = get_db()
    member = db.execute('SELECT id, full_name FROM users WHERE id = ? AND status = "active"', (user_id,)).fetchone()
    if not member:
        flash('Anggota aktif tidak ditemukan.', 'danger')
        return redirect(request.referrer or url_for('admin.users'))
    # Check if already has entry for today
    existing = db.execute('''
        SELECT id FROM attendance 
        WHERE user_id = ? AND date(scan_time) = date('now', 'localtime')
    ''', (user_id,)).fetchone()
    
    if existing:
        db.execute('UPDATE attendance SET status = ?, marked_by = ? WHERE id = ?',
                   (status, session['user_id'], existing['id']))
    else:
        db.execute('INSERT INTO attendance (user_id, status, marked_by) VALUES (?, ?, ?)',
                   (user_id, status, session['user_id']))
    
    db.commit()
    send_dual_notification(
        user_id, 'Status presensi diperbarui',
        f'Presensi Anda hari ini dicatat sebagai {status}.',
        'info', url='/attendance/', category='attendance'
    )
    flash(f'Presensi anggota berhasil diperbarui ke: {status}', 'success')
    return redirect(request.referrer or url_for('admin.users'))

@admin_bp.route('/attendance/update/<int:id>/<string:status>', methods=['POST'])
@admin_required
def update_attendance(id, status):
    if status not in {'Hadir', 'Izin', 'Sakit', 'Alpha'}:
        flash('Status presensi tidak valid.', 'danger')
        return redirect(url_for('admin.attendance'))
    db = get_db()
    entry = db.execute('SELECT user_id FROM attendance WHERE id = ?', (id,)).fetchone()
    if not entry:
        flash('Catatan presensi tidak ditemukan.', 'danger')
        return redirect(url_for('admin.attendance'))
    db.execute('UPDATE attendance SET status = ?, marked_by = ? WHERE id = ?',
               (status, session['user_id'], id))
    db.commit()
    send_dual_notification(
        entry['user_id'], 'Status presensi diperbarui',
        f'Presensi Anda diperbarui menjadi {status}.',
        'info', url='/attendance/', category='attendance'
    )
    flash('Log presensi berhasil diperbarui.', 'success')
    return redirect(url_for('admin.attendance'))

@admin_bp.route('/attendance/reset-today', methods=['POST'])
@admin_required
def reset_today_attendance():
    db = get_db()
    db.execute("DELETE FROM attendance WHERE date(scan_time) = date('now', 'localtime')")
    db.commit()
    flash('Seluruh data presensi hari ini telah direset.', 'warning')
    return redirect(url_for('admin.attendance'))
