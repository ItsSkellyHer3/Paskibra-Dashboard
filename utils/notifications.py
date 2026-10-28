from database import get_db
from flask import Flask

def add_notification(user_id, title, message, n_type='info', url=None, category='general'):
    """
    Adds a notification to the database.
    user_id: ID of the user to notify. If None, it's for all admins.
    n_type: info, success, warning, alert
    url: Optional URL to open when notification is clicked
    category: announcement, forum, schedule, approval, bug, suggestion, general
    """
    db = get_db()
    
    # If it's a specific user, check their notification preferences
    if user_id:
        user = db.execute('SELECT preferences FROM users WHERE id = ?', (user_id,)).fetchone()
        if user and user['preferences']:
            import json
            try:
                prefs = json.loads(user['preferences'])
                notif_prefs = prefs.get('notif_types', {})
                # If the category is explicitly disabled, don't save
                if notif_prefs.get(category) is False:
                    return
            except:
                pass

    db.execute('''
        INSERT INTO notifications (user_id, title, message, type, url, category)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, title, message, n_type, url, category))
    db.commit()

def notify_admins(title, message, n_type='info', url=None, category='general'):
    """
    Sends a notification to all admin users.
    """
    add_notification(None, title, message, n_type, url, category)

def notify_user(user_id, title, message, n_type='info', url=None, category='general'):
    """
    Sends a notification to a specific user.
    """
    add_notification(user_id, title, message, n_type, url, category)
