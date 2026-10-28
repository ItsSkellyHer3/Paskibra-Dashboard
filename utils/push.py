import base64
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from flask import current_app

from database import get_db

logger = logging.getLogger(__name__)


def _vapid_credentials():
    """Load configured VAPID keys or create a stable local key pair once."""
    configured_private = os.environ.get('VAPID_PRIVATE_KEY')
    private_path = os.environ.get('VAPID_PRIVATE_KEY_PATH')

    if private_path:
        vapid = Vapid.from_file(private_key_file=private_path)
        signing_key = private_path
    elif configured_private:
        if configured_private.lstrip().startswith('-----BEGIN'):
            private_key = serialization.load_pem_private_key(
                configured_private.encode('utf-8'), password=None
            )
            vapid = Vapid()
            vapid.private_key = private_key
        else:
            vapid = Vapid.from_string(configured_private)
        signing_key = vapid
    else:
        key_path = Path(current_app.instance_path) / 'vapid_private.pem'
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            vapid = Vapid.from_file(private_key_file=str(key_path))
        else:
            vapid = Vapid()
            vapid.generate_keys()
            key_path.write_bytes(vapid.private_pem())
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        signing_key = str(key_path)

    public_bytes = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(public_bytes).decode('ascii').rstrip('=')
    configured_public = os.environ.get('VAPID_PUBLIC_KEY')
    if configured_public and configured_public != public_key:
        raise RuntimeError('VAPID_PUBLIC_KEY does not match VAPID_PRIVATE_KEY.')

    return public_key, signing_key


def get_vapid_public_key():
    return _vapid_credentials()[0]


def _send_webpush(subscription_json, payload):
    try:
        _, signing_key = _vapid_credentials()
        webpush(
            subscription_info=json.loads(subscription_json),
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=signing_key,
            vapid_claims={
                'sub': os.environ.get('VAPID_SUBJECT', 'mailto:admin@paskibra-app.com')
            },
            ttl=60 * 60 * 24,
        )
        return 'sent'
    except WebPushException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status in (404, 410):
            return 'expired'
        logger.warning('Push service rejected a notification (HTTP %s).', status or 'unknown')
    except Exception as exc:
        logger.warning('Push notification failed (%s).', type(exc).__name__)
    return 'failed'


def _subscription_rows(user_id=None, admins_only=False, active_only=False):
    db = get_db()
    clauses = []
    params = []
    if admins_only:
        clauses.append("u.role IN ('Owner', 'Admin', 'Super Admin', 'Moderator')")
    if active_only:
        clauses.append("u.status = 'active'")
    if user_id is not None:
        clauses.append('ps.user_id = ?')
        params.append(user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    return db.execute(f'''
        SELECT ps.id, ps.user_id, ps.subscription_json, u.preferences
        FROM push_subscriptions ps
        JOIN users u ON u.id = ps.user_id
        {where}
    ''', params).fetchall()


def _deliver(rows, title, message, url=None, category=None):
    db = get_db()
    payload = {
        'title': title,
        'body': message,
        'icon': '/static/img/paskiblogo.jpg',
        'data': {'url': url or '/'},
    }
    counts = {'sent': 0, 'expired': 0, 'failed': 0, 'skipped': 0}
    expired_ids = []

    for row in rows:
        if category and row['preferences']:
            try:
                preferences = json.loads(row['preferences'])
                if preferences.get('notif_types', {}).get(category) is False:
                    counts['skipped'] += 1
                    continue
            except (TypeError, ValueError):
                pass
        result = _send_webpush(row['subscription_json'], payload)
        counts[result] += 1
        if result == 'expired':
            expired_ids.append(row['id'])

    if expired_ids:
        placeholders = ', '.join('?' for _ in expired_ids)
        db.execute(f'DELETE FROM push_subscriptions WHERE id IN ({placeholders})', expired_ids)
        db.commit()
    return counts


def send_push_notification(user_id, title, message, url=None, category=None):
    """Send a web push notification to one user's registered devices."""
    rows = _subscription_rows(user_id=user_id, admins_only=user_id is None)
    return _deliver(rows, title, message, url, category)


def send_dual_notification(user_id, title, message, n_type='info', url=None, category='general'):
    """Save an in-app notification and deliver a browser push when subscribed."""
    from utils.notifications import add_notification

    add_notification(user_id, title, message, n_type, url, category)
    if user_id is not None:
        user = get_db().execute(
            'SELECT preferences FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if user and user['preferences']:
            try:
                preferences = json.loads(user['preferences'])
                if preferences.get('notif_types', {}).get(category) is False:
                    return {'sent': 0, 'expired': 0, 'failed': 0, 'skipped': 1}
            except (TypeError, ValueError):
                pass
    return send_push_notification(user_id, title, message, url, category)


def broadcast_push_notification(title, message, url=None, category='announcement'):
    """Send a push to subscribed active members who allow this category."""
    return _deliver(
        _subscription_rows(active_only=True), title, message, url, category
    )
