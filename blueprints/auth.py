from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db
from utils.notifications import notify_admins
from utils.push import send_dual_notification
import uuid
import datetime
import json

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
TERMS_VERSION = '2026-10-25'


@auth_bp.route('/terms')
def terms():
    return render_template('auth/legal.html', document_type='terms', terms_version=TERMS_VERSION)


@auth_bp.route('/privacy')
def privacy():
    return render_template('auth/legal.html', document_type='privacy', terms_version=TERMS_VERSION)


def _registration_state():
    rows = get_db().execute('''
        SELECT key, value FROM system_settings
        WHERE key IN ('registration_open', 'registration_closed_reason')
    ''').fetchall()
    settings = {row['key']: row['value'] for row in rows}
    reason = (settings.get('registration_closed_reason') or '').strip()
    return settings.get('registration_open', '1') == '1', reason or 'Pendaftaran anggota sedang ditutup. Silakan coba lagi nanti.'


@auth_bp.route('/registration-closed')
def registration_closed():
    is_open, reason = _registration_state()
    if is_open:
        return redirect(url_for('auth.register'))
    return render_template('auth/registration_closed.html', reason=reason)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and check_password_hash(user['password'], password):
            if user['status'] == 'rejected':
                flash('Pendaftaran akun Anda belum disetujui. Hubungi pengurus untuk informasi.', 'danger')
                return render_template('auth/login.html')
            if user['status'] == 'suspended':
                flash('Your account is suspended.', 'danger')
                return render_template('auth/login.html')
            
            if user['role'] in ['Owner', 'Admin', 'Super Admin', 'Moderator']:
                flash('Please use the Admin Login portal.', 'warning')
                return redirect(url_for('auth.admin_login'))
                
            session.permanent = request.form.get('remember') == 'on'
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['class'] = user['class']
            session['avatar'] = user['avatar']
            
            # Load preferences
            try:
                session['prefs'] = json.loads(user['preferences']) if user['preferences'] else {}
            except:
                session['prefs'] = {}
            
            db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
            db.commit()
            
            if user['status'] == 'pending':
                return redirect(url_for('auth.qr_wait'))
                
            return redirect(url_for('dashboard.index'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('auth/login.html')

@auth_bp.route('/qr-login-verify', methods=['POST'])
def qr_login_verify():
    data = request.json
    qr_uuid = data.get('qr_uuid')
    
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE qr_code_uuid = ?', (qr_uuid,)).fetchone()
    
    if user:
        if user['status'] != 'active':
            return {'status': 'error', 'message': 'Akun Anda belum aktif atau ditangguhkan.'}
            
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['full_name'] = user['full_name']
        session['role'] = user['role']
        session['class'] = user['class']
        session['avatar'] = user['avatar']
        
        # Load preferences
        try:
            session['prefs'] = json.loads(user['preferences']) if user['preferences'] else {}
        except:
            session['prefs'] = {}
        
        db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
        db.commit()
        
        return {'status': 'success', 'message': f'Selamat datang, {user["full_name"]}!', 'redirect': url_for('dashboard.index')}
    else:
        return {'status': 'error', 'message': 'QR Code tidak valid atau tidak terdaftar.'}

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if 'user_id' in session and session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']:
        return redirect(url_for('admin.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and check_password_hash(user['password'], password):
            if user['role'] not in ['Owner', 'Admin', 'Super Admin', 'Moderator']:
                flash('This portal is for authorized administrators only.', 'danger')
                return redirect(url_for('auth.login'))
                
            session.permanent = request.form.get('remember') == 'on'
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['class'] = user['class']
            session['avatar'] = user['avatar']
            
            # Load preferences
            try:
                session['prefs'] = json.loads(user['preferences']) if user['preferences'] else {}
            except:
                session['prefs'] = {}
            
            db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
            db.commit()
            
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid administrator credentials.', 'danger')
            
    return render_template('auth/admin_login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    is_open, _ = _registration_state()
    if not is_open:
        return redirect(url_for('auth.registration_closed'))

    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        class_name = (request.form.get('class') or '').strip()
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if not all((full_name, class_name, username, password)):
            flash('Lengkapi semua kolom yang wajib diisi.', 'warning')
            return render_template('auth/register.html')
        if len(full_name) > 100 or len(class_name) > 60 or len(username) < 3 or len(username) > 32:
            flash('Periksa kembali panjang nama, kelas, dan username.', 'warning')
            return render_template('auth/register.html')
        if len(password) < 8:
            flash('Kata sandi harus memiliki minimal 8 karakter.', 'warning')
            return render_template('auth/register.html')
        if request.form.get('terms') != 'on' or request.form.get('consent_confirmed') != 'on':
            flash('Baca informasi privasi dan konfirmasikan persetujuan sebelum melanjutkan.', 'warning')
            return render_template('auth/register.html')
        
        db = get_db()
        # Check if username exists
        exists = db.execute('SELECT 1 FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
        if exists:
            flash('Username already taken.', 'warning')
            return render_template('auth/register.html')
            
        pw_hash = generate_password_hash(password)
        qr_uuid = str(uuid.uuid4())
        att_qr_uuid = str(uuid.uuid4())
        
        db.execute('''
            INSERT INTO users (full_name, class, username, password, role, status, qr_code_uuid, attendance_qr_uuid, terms_accepted_at, terms_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ''', (full_name, class_name, username, pw_hash, 'member', 'pending', qr_uuid, att_qr_uuid, TERMS_VERSION))
        db.commit()
        
        # Notify Admins about new registration
        send_dual_notification(None, 'Pendaftaran Baru', f'{full_name} ({class_name}) telah mendaftar dan menunggu persetujuan.', 'warning', url='/admin/pending', category='approval')
        
        # Get the new user ID
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        session['pending_user_id'] = user['id']
        
        flash('Registration successful! Please show your QR Code to an Admin for approval.', 'success')
        return redirect(url_for('auth.qr_wait'))
        
    return render_template('auth/register.html')

@auth_bp.route('/qr-wait')
def qr_wait():
    user_id = session.get('pending_user_id')
    if not user_id:
        if 'user_id' in session:
            user_id = session['user_id']
        else:
            return redirect(url_for('auth.login'))
    
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if not user:
        return redirect(url_for('auth.login'))
        
    if user['status'] == 'active':
        session.pop('pending_user_id', None)
        
        # Auto-login: Set all session variables
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['full_name'] = user['full_name']
        session['role'] = user['role']
        session['class'] = user['class']
        session['avatar'] = user['avatar']
        
        # Load preferences
        try:
            session['prefs'] = json.loads(user['preferences']) if user['preferences'] else {}
        except:
            session['prefs'] = {}
            
        # Update last login
        db.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
        db.commit()
        
        flash('Account Anda telah disetujui! Selamat datang di dashboard.', 'success')
        return redirect(url_for('dashboard.index'))
        
    from utils.qr_gen import generate_qr_base64
    qr_image = generate_qr_base64(user['qr_code_uuid'])
    
    return render_template('auth/qr_wait.html', user=user, qr_image=qr_image)


@auth_bp.route('/qr-wait-status')
def qr_wait_status():
    user_id = session.get('pending_user_id')
    if not user_id and 'user_id' in session:
        user_id = session['user_id']
    if not user_id:
        return {'status': 'missing'}, 401
    user = get_db().execute('SELECT status FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return {'status': 'missing'}, 404
    return {'status': user['status']}

@auth_bp.route('/pending')
def pending():
    return redirect(url_for('auth.qr_wait'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
