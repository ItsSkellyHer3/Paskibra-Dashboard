from flask import Blueprint, render_template, session, request, redirect, url_for, flash
from database import get_db
from utils.decorators import login_required, admin_required
from utils.qr_gen import generate_qr_base64
from utils.push import send_dual_notification
from datetime import datetime, timedelta

attendance_bp = Blueprint('attendance', __name__, url_prefix='/attendance')

@attendance_bp.route('/')
@login_required
def index():
    db = get_db()
    
    # Personal QR for members
    user_qr = db.execute('SELECT attendance_qr_uuid FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    qr_code = generate_qr_base64(user_qr['attendance_qr_uuid']) if user_qr else None
    
    # Today's personal status
    today_status = db.execute('''
        SELECT * FROM attendance 
        WHERE user_id = ? AND date(scan_time) = date('now', 'localtime')
        LIMIT 1
    ''', (session['user_id'],)).fetchone()
    
    # Personal history
    history = db.execute('''
        SELECT * FROM attendance 
        WHERE user_id = ? 
        ORDER BY scan_time DESC
        LIMIT 30
    ''', (session['user_id'],)).fetchall()
    
    # Personal stats
    stats_row = db.execute('''
        SELECT
            COALESCE(SUM(status = 'Hadir'), 0) AS hadir,
            COALESCE(SUM(status = 'Izin'), 0) AS izin,
            COALESCE(SUM(status = 'Sakit'), 0) AS sakit,
            COALESCE(SUM(status = 'Alpha'), 0) AS alpha
        FROM attendance WHERE user_id = ?
    ''', (session['user_id'],)).fetchone()
    personal_stats = dict(stats_row)

    # Weekly Rekap (Last 7 days)
    weekly_start = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    weekly_counts = {
        row['day']: row['count']
        for row in db.execute('''
            SELECT date(scan_time) AS day, COUNT(*) AS count
            FROM attendance
            WHERE user_id = ? AND status = 'Hadir'
              AND date(scan_time) >= ? AND date(scan_time) <= date('now', 'localtime')
            GROUP BY date(scan_time)
        ''', (session['user_id'], weekly_start)).fetchall()
    }
    weekly_data = []
    for i in range(6, -1, -1):
        target_date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        day_name = (datetime.now() - timedelta(days=i)).strftime('%a')
        count = weekly_counts.get(target_date, 0)
        weekly_data.append({'day': day_name, 'count': count, 'date': target_date})
    
    # Global Summary for Admin
    global_stats = {
        'total_active': 0,
        'hadir': 0,
        'izin': 0,
        'sakit': 0,
        'alpha': 0,
        'belum_absen': 0
    }
    
    members = []
    if session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']:
        # Filter and Search are handled in frontend for speed, but we can provide initial data
        members = db.execute('''
            SELECT u.id, u.full_name, u.class, u.avatar, u.role, a.status as today_status, a.scan_time as today_time
            FROM users u
            LEFT JOIN attendance a ON u.id = a.user_id AND date(a.scan_time) = date('now', 'localtime')
            WHERE u.status = 'active'
            ORDER BY u.full_name ASC
        ''').fetchall()
        
        global_stats['total_active'] = len(members)
        for m in members:
            if m['today_status'] == 'Hadir': global_stats['hadir'] += 1
            elif m['today_status'] == 'Izin': global_stats['izin'] += 1
            elif m['today_status'] == 'Sakit': global_stats['sakit'] += 1
            elif m['today_status'] == 'Alpha': global_stats['alpha'] += 1
            else: global_stats['belum_absen'] += 1
            
    now_date = datetime.now().strftime('%d %B %Y')
    
    return render_template('attendance/index.html', 
                           history=history, 
                           stats=personal_stats, 
                           global_stats=global_stats,
                           qr_code=qr_code, 
                           today_status=today_status,
                           weekly_data=weekly_data,
                           members=members,
                           now_date=now_date)

@attendance_bp.route('/reset', methods=['POST'])
@admin_required
def reset_today():
    db = get_db()
    db.execute("DELETE FROM attendance WHERE date(scan_time) = date('now', 'localtime')")
    db.commit()
    flash('Absensi hari ini telah direset.', 'success')
    return redirect(url_for('attendance.index'))

@attendance_bp.route('/member/<int:user_id>')
@admin_required
def member_detail(user_id):
    db = get_db()
    member = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not member:
        flash('Anggota tidak ditemukan.', 'danger')
        return redirect(url_for('attendance.index'))
    
    history = db.execute('''
        SELECT * FROM attendance 
        WHERE user_id = ? 
        ORDER BY scan_time DESC
        LIMIT 50
    ''', (user_id,)).fetchall()
    
    stats = {
        'hadir': db.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ? AND status = "Hadir"', (user_id,)).fetchone()[0],
        'izin': db.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ? AND status = "Izin"', (user_id,)).fetchone()[0],
        'sakit': db.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ? AND status = "Sakit"', (user_id,)).fetchone()[0],
        'alpha': db.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ? AND status = "Alpha"', (user_id,)).fetchone()[0],
    }
    
    return render_template('attendance/detail.html', member=member, history=history, stats=stats)

@attendance_bp.route('/scanner')
@admin_required
def scanner():
    return render_template('attendance/qr_scanner.html')

@attendance_bp.route('/scan', methods=['POST'])
@admin_required
def scan():
    qr_uuid = request.json.get('qr_uuid')
    db = get_db()
    
    # Strictly Attendance QR ONLY
    user = db.execute('SELECT * FROM users WHERE attendance_qr_uuid = ?', (qr_uuid,)).fetchone()
    
    if not user:
        # Check if they accidentally scanned the identity QR
        is_identity = db.execute('SELECT 1 FROM users WHERE qr_code_uuid = ?', (qr_uuid,)).fetchone()
        if is_identity:
            return {'status': 'error', 'message': 'Ini adalah QR Identitas. Gunakan QR Presensi (Digital ID Biru) untuk absensi.'}
        return {'status': 'error', 'message': 'QR Code tidak valid.'}

    if user['status'] != 'active':
        return {'status': 'error', 'message': f'Akun {user["full_name"]} tidak aktif ({user["status"]}).'}

    # Check if already scanned today
    already_scanned = db.execute('''
        SELECT id FROM attendance 
        WHERE user_id = ? AND DATE(scan_time) = DATE('now', 'localtime')
    ''', (user['id'],)).fetchone()
    
    if already_scanned:
        return {'status': 'warning', 'message': f'{user["full_name"]} sudah absen hari ini.', 'user': dict(user)}

    db.execute('INSERT INTO attendance (user_id, marked_by) VALUES (?, ?)', (user['id'], session['user_id']))
    db.commit()

    send_dual_notification(
        user['id'], 'Presensi berhasil',
        f'Kehadiran Anda hari ini telah dicatat oleh petugas.',
        'success', url='/attendance/', category='attendance'
    )
    
    return {
        'status': 'success', 
        'message': f'Presensi Berhasil: {user["full_name"]}',
        'user': {
            'full_name': user['full_name'],
            'class': user['class'],
            'avatar': user['avatar']
        }
    }

@attendance_bp.route('/mark', methods=['POST'])
@admin_required
def mark():
    try:
        user_id = int(request.form.get('user_id', ''))
    except (TypeError, ValueError):
        flash('Anggota tidak valid.', 'danger')
        return redirect(url_for('attendance.index'))
    status = request.form.get('status')
    if status not in {'Hadir', 'Izin', 'Sakit', 'Alpha'}:
        flash('Status presensi tidak valid.', 'danger')
        return redirect(url_for('attendance.index'))
    db = get_db()
    member = db.execute('SELECT id, full_name FROM users WHERE id = ?', (user_id,)).fetchone()
    if not member:
        flash('Anggota tidak ditemukan.', 'danger')
        return redirect(url_for('attendance.index'))
    
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
    flash(f'Presensi {member["full_name"]} diperbarui: {status}.', 'success')
    return redirect(url_for('attendance.index'))

