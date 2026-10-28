from flask import Blueprint, jsonify, session, request, render_template
from database import get_db
from utils.decorators import login_required
from utils.push import get_vapid_public_key, send_push_notification
import json

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')

@notifications_bp.route('/')
@login_required
def get_notifications():
    db = get_db()
    # Fetch user specific notifications + global admin notifications if user is admin
    user_id = session['user_id']
    is_admin = session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']
    
    if is_admin:
        notifications = db.execute('''
            SELECT * FROM notifications 
            WHERE user_id = ? OR user_id IS NULL
            ORDER BY created_at DESC LIMIT 50
        ''', (user_id,)).fetchall()
    else:
        notifications = db.execute('''
            SELECT * FROM notifications 
            WHERE user_id = ? 
            ORDER BY created_at DESC LIMIT 50
        ''', (user_id,)).fetchall()
        
    return jsonify([dict(n) for n in notifications])

@notifications_bp.route('/unread-count')
@login_required
def unread_count():
    db = get_db()
    user_id = session['user_id']
    is_admin = session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']
    
    if is_admin:
        count = db.execute('''
            SELECT COUNT(*) FROM notifications 
            WHERE (user_id = ? OR user_id IS NULL) AND is_read = 0
        ''', (user_id,)).fetchone()[0]
    else:
        count = db.execute('''
            SELECT COUNT(*) FROM notifications 
            WHERE user_id = ? AND is_read = 0
        ''', (user_id,)).fetchone()[0]
        
    return jsonify({'count': count})

@notifications_bp.route('/mark-read', methods=['POST'])
@login_required
def mark_read():
    notification_id = request.json.get('id')
    db = get_db()
    if notification_id:
        db.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (notification_id,))
    else:
        # Mark all as read
        user_id = session['user_id']
        is_admin = session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']
        if is_admin:
            db.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ? OR user_id IS NULL', (user_id,))
        else:
            db.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (user_id,))
            
    db.commit()
    return jsonify({'status': 'success'})

@notifications_bp.route('/page')
@login_required
def index():
    return render_template('notifications/index.html')

@notifications_bp.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    subscription_info = request.get_json(silent=True)
    if not isinstance(subscription_info, dict):
        return jsonify({'status': 'error', 'message': 'Data langganan tidak valid.'}), 400
    endpoint = subscription_info.get('endpoint')
    keys = subscription_info.get('keys')
    if (not isinstance(endpoint, str) or not endpoint.startswith('https://')
            or not isinstance(keys, dict) or not keys.get('p256dh') or not keys.get('auth')):
        return jsonify({'status': 'error', 'message': 'Data langganan push tidak lengkap.'}), 400

    normalized = {
        'endpoint': endpoint,
        'expirationTime': subscription_info.get('expirationTime'),
        'keys': {'p256dh': keys['p256dh'], 'auth': keys['auth']},
    }
    serialized = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
    db = get_db()
    rows = db.execute('SELECT id, user_id, subscription_json FROM push_subscriptions').fetchall()
    matching_id = None
    for row in rows:
        try:
            same_endpoint = json.loads(row['subscription_json']).get('endpoint') == endpoint
        except (TypeError, ValueError):
            same_endpoint = False
        if same_endpoint:
            if row['user_id'] == session['user_id']:
                matching_id = row['id']
            else:
                db.execute('DELETE FROM push_subscriptions WHERE id = ?', (row['id'],))
    if matching_id:
        db.execute('UPDATE push_subscriptions SET subscription_json = ? WHERE id = ?', (serialized, matching_id))
    else:
        db.execute('INSERT INTO push_subscriptions (user_id, subscription_json) VALUES (?, ?)',
                   (session['user_id'], serialized))
    db.commit()
    return jsonify({'status': 'success'})

@notifications_bp.route('/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    subscription_info = request.get_json(silent=True) or {}
    endpoint = subscription_info.get('endpoint')
    if not isinstance(endpoint, str):
        return jsonify({'status': 'error', 'message': 'Endpoint langganan tidak valid.'}), 400
    db = get_db()
    rows = db.execute('SELECT id, subscription_json FROM push_subscriptions WHERE user_id = ?',
                      (session['user_id'],)).fetchall()
    for row in rows:
        try:
            if json.loads(row['subscription_json']).get('endpoint') == endpoint:
                db.execute('DELETE FROM push_subscriptions WHERE id = ?', (row['id'],))
        except (TypeError, ValueError):
            continue
    db.commit()
    return jsonify({'status': 'success'})


@notifications_bp.route('/public-key')
@login_required
def public_key():
    try:
        return jsonify({'publicKey': get_vapid_public_key()})
    except Exception:
        return jsonify({'status': 'error', 'message': 'Konfigurasi notifikasi belum siap.'}), 503


@notifications_bp.route('/test-push', methods=['POST'])
@login_required
def test_push():
    result = send_push_notification(
        session['user_id'], 'Notifikasi uji',
        'Notifikasi browser sudah terhubung ke perangkat ini.',
        url='/profile/settings',
    )
    if result['sent']:
        return jsonify({'status': 'success', 'sent': result['sent']})
    if result['failed']:
        return jsonify({'status': 'error', 'message': 'Layanan push menolak notifikasi. Coba aktifkan ulang notifikasi.'}), 502
    return jsonify({'status': 'error', 'message': 'Belum ada perangkat yang terdaftar untuk akun ini.'}), 409

@notifications_bp.route('/delete', methods=['POST'])
@login_required
def delete_notification():
    notification_id = request.json.get('id')
    db = get_db()
    if notification_id:
        user_id = session['user_id']
        is_admin = session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']
        if is_admin:
            db.execute('DELETE FROM notifications WHERE id = ? AND (user_id = ? OR user_id IS NULL)', (notification_id, user_id))
        else:
            db.execute('DELETE FROM notifications WHERE id = ? AND user_id = ?', (notification_id, user_id))
        db.commit()
    return jsonify({'status': 'success'})

@notifications_bp.route('/clear', methods=['POST'])
@login_required
def clear_notifications():
    db = get_db()
    user_id = session['user_id']
    is_admin = session.get('role') in ['Owner', 'Admin', 'Super Admin', 'Moderator']
    if is_admin:
        db.execute('DELETE FROM notifications WHERE user_id = ? OR user_id IS NULL', (user_id,))
    else:
        db.execute('DELETE FROM notifications WHERE user_id = ?', (user_id,))
    db.commit()
    return jsonify({'status': 'success'})
