from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from database import get_db
from utils.decorators import login_required
from utils.qr_gen import generate_qr_base64
from database import delete_user_data
from werkzeug.security import check_password_hash
import json
import re

profile_bp = Blueprint('profile', __name__, url_prefix='/profile')

import os
import uuid
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'static/uploads/'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

from datetime import datetime, timedelta

@profile_bp.route('/')
@login_required
def view():
    db = get_db()
    user = db.execute('''
        SELECT u.*, 
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Hadir") as hadir,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Izin") as izin,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Sakit") as sakit,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Alpha") as alpha
        FROM users u 
        WHERE u.id = ?
    ''', (session['user_id'],)).fetchone()
    
    user_dict = dict(user)
    is_online = False
    if user['last_active']:
        last_active_dt = datetime.strptime(user['last_active'], '%Y-%m-%d %H:%M:%S.%f') if '.' in user['last_active'] else datetime.strptime(user['last_active'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() - last_active_dt < timedelta(minutes=5):
            is_online = True
    user_dict['is_online'] = is_online
    
    qr_code_image = generate_qr_base64(user['qr_code_uuid'])
    return render_template('profile/view.html', user=user_dict, qr_code_image=qr_code_image, is_own=True)

@profile_bp.route('/update-status', methods=['POST'])
@login_required
def update_status():
    status = request.form.get('status')
    if status is not None:
        db = get_db()
        db.execute('UPDATE users SET status_message = ? WHERE id = ?', (status, session['user_id']))
        db.commit()
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

@profile_bp.route('/upload-avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        flash('Tidak ada file dipilih', 'danger')
        return redirect(url_for('profile.settings'))
    
    file = request.files['avatar']
    if file.filename == '':
        flash('Tidak ada file dipilih', 'danger')
        return redirect(url_for('profile.settings'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(f"avatar_{session['user_id']}_{uuid.uuid4().hex[:12]}_{file.filename}")
        file.save(os.path.join(UPLOAD_FOLDER, filename))
        
        db = get_db()
        db.execute('UPDATE users SET avatar = ? WHERE id = ?', (filename, session['user_id']))
        db.commit()
        session['avatar'] = filename
        flash('Foto profil berhasil diperbarui!', 'success')
    else:
        flash('Format file tidak didukung.', 'danger')
        
    return redirect(url_for('profile.settings'))

@profile_bp.route('/user/<int:user_id>')
@login_required
def view_user(user_id):
    db = get_db()
    user = db.execute('''
        SELECT u.*, 
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Hadir") as hadir,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Izin") as izin,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Sakit") as sakit,
        (SELECT COUNT(*) FROM attendance WHERE user_id = u.id AND status = "Alpha") as alpha
        FROM users u 
        WHERE u.id = ?
    ''', (user_id,)).fetchone()
    
    if not user:
        flash('Anggota tidak ditemukan.', 'danger')
        return redirect(url_for('members.list'))
    
    user_dict = dict(user)
    is_online = False
    if user['last_active']:
        last_active_dt = datetime.strptime(user['last_active'], '%Y-%m-%d %H:%M:%S.%f') if '.' in user['last_active'] else datetime.strptime(user['last_active'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() - last_active_dt < timedelta(minutes=5):
            is_online = True
    user_dict['is_online'] = is_online
    
    # Fetch attendance history
    history = db.execute('''
        SELECT * FROM attendance 
        WHERE user_id = ? 
        ORDER BY scan_time DESC 
        LIMIT 10
    ''', (user_id,)).fetchall()
    
    qr_code_image = generate_qr_base64(user['qr_code_uuid'])
    # Only show QR to self or admins
    show_qr = (user_id == session['user_id'] or session['role'] in ['Owner', 'Admin', 'Super Admin', 'Moderator'])
    
    return render_template('profile/view.html', 
                           user=user_dict, 
                           history=history,
                           qr_code_image=qr_code_image if show_qr else None,
                           is_own=(user_id == session['user_id']))

@profile_bp.route('/toggle-theme', methods=['POST'])
@login_required
def toggle_theme():
    db = get_db()
    user = db.execute('SELECT preferences FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    try:
        prefs = json.loads(user['preferences']) if user['preferences'] else {}
    except:
        prefs = {}
        
    prefs['dark_mode'] = not prefs.get('dark_mode', False)
    
    db.execute('UPDATE users SET preferences = ? WHERE id = ?',
               (json.dumps(prefs), session['user_id']))
    db.commit()
    session['prefs'] = prefs
    
    return jsonify({'status': 'success', 'dark_mode': prefs['dark_mode']})

@profile_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    try:
        current_prefs = json.loads(user['preferences']) if user['preferences'] else {}
    except:
        current_prefs = {}
    
    if request.method == 'POST':
        # Check if it's a preferences update (JSON) or profile update (Form)
        if request.is_json:
            new_prefs = request.json
            db.execute('UPDATE users SET preferences = ? WHERE id = ?',
                       (json.dumps(new_prefs), session['user_id']))
            db.commit()
            session['prefs'] = new_prefs
            return jsonify({'status': 'success'})
            
        full_name = request.form.get('full_name')
        bio = request.form.get('bio')
        class_name = request.form.get('class')
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone')
        birth_date = request.form.get('birth_date')
        nickname = request.form.get('nickname')
        
        if not username or not re.fullmatch(r'[A-Za-z0-9_]{3,24}', username):
            flash('Username harus 3–24 karakter dan hanya boleh berisi huruf, angka, atau garis bawah.', 'danger')
            return redirect(url_for('profile.settings'))
        collision = db.execute(
            'SELECT id FROM users WHERE username = ? COLLATE NOCASE AND id != ?',
            (username, session['user_id'])
        ).fetchone()
        if collision:
            flash('Username tersebut sudah digunakan.', 'danger')
            return redirect(url_for('profile.settings'))
        if not class_name or len(class_name.strip()) > 60:
            flash('Kelas wajib diisi (maksimal 60 karakter).', 'danger')
            return redirect(url_for('profile.settings'))

        db.execute('''
            UPDATE users 
            SET full_name = ?, bio = ?, class = ?, username = ?, phone = ?, birth_date = ?, nickname = ? 
            WHERE id = ?
        ''', (full_name, bio, class_name.strip(), username, phone, birth_date, nickname, session['user_id']))
        db.commit()
        
        # Update session data
        session['full_name'] = full_name
        session['class'] = class_name.strip()
        session['username'] = username
        
        flash('Profil berhasil diperbarui!', 'success')
        return redirect(url_for('profile.view'))
        
    return render_template('profile/settings.html', user=user, prefs=current_prefs)

@profile_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    db = get_db()
    user = db.execute('SELECT id, username, password, full_name FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    password = request.form.get('password', '')
    username_confirmation = request.form.get('username_confirmation', '').strip()

    if not user:
        session.clear()
        return redirect(url_for('auth.login'))
    if user['password']:
        if not password or not check_password_hash(user['password'], password):
            flash('Kata sandi tidak cocok. Akun belum dihapus.', 'danger')
            return redirect(url_for('profile.settings'))
    else:
        expected_confirmation = user['username'] or user['full_name']
        if username_confirmation != expected_confirmation:
            flash('Teks konfirmasi tidak cocok. Akun belum dihapus.', 'danger')
            return redirect(url_for('profile.settings'))

    delete_user_data(db, user['id'])
    db.commit()
    session.clear()
    flash('Akun dan data pribadi Anda telah dihapus.', 'success')
    return redirect(url_for('auth.login'))
