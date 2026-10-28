from functools import wraps
from flask import session, redirect, url_for, flash, g
from database import get_db

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        
        # Check if user is active
        db = get_db()
        user = db.execute('SELECT status FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if not user or user['status'] != 'active':
            if user and user['status'] == 'pending':
                return redirect(url_for('auth.pending'))
            session.clear()
            flash('Your account is suspended or inactive.', 'danger')
            return redirect(url_for('auth.login'))
            
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
            
        db = get_db()
        user = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if not user or user['role'] not in ['Owner', 'Admin', 'Super Admin', 'Moderator']:
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
            
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
            
        db = get_db()
        user = db.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if not user or user['role'] not in ['Owner', 'Super Admin']:
            flash('Owner or Super Admin access required.', 'danger')
            return redirect(url_for('admin.dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function
