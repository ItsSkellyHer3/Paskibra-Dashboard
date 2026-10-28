from flask import Blueprint, render_template
from database import get_db
from utils.decorators import login_required

members_bp = Blueprint('members', __name__, url_prefix='/members')

from datetime import datetime, timedelta

@members_bp.route('/')
@login_required
def list():
    db = get_db()
    # Fetch all active members with more details
    members = db.execute('''
        SELECT id, full_name, class, role, avatar, status, status_message, last_active, current_activity 
        FROM users 
        WHERE status = "active" 
        ORDER BY role DESC, full_name ASC
    ''').fetchall()
    
    # Process members to add 'is_online' flag
    processed_members = []
    now = datetime.now()
    for m in members:
        m_dict = dict(m)
        is_online = False
        if m['last_active']:
            # Assume online if active in last 5 minutes
            last_active_dt = datetime.strptime(m['last_active'], '%Y-%m-%d %H:%M:%S.%f') if '.' in m['last_active'] else datetime.strptime(m['last_active'], '%Y-%m-%d %H:%M:%S')
            if now - last_active_dt < timedelta(minutes=5):
                is_online = True
        m_dict['is_online'] = is_online
        processed_members.append(m_dict)
    
    # Get unique classes and roles for filters
    classes = db.execute('SELECT DISTINCT class FROM users WHERE status = "active"').fetchall()
    roles = db.execute('SELECT DISTINCT role FROM users WHERE status = "active"').fetchall()
    
    return render_template('members/list.html', 
                           members=processed_members, 
                           classes=[c['class'] for c in classes],
                           roles=[r['role'] for r in roles])
