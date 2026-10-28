from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from utils.decorators import login_required, admin_required
from utils.notifications import add_notification
from utils.push import broadcast_push_notification
from datetime import datetime, timedelta

schedule_bp = Blueprint('schedule', __name__, url_prefix='/schedule')

@schedule_bp.route('/')
@login_required
def list():
    db = get_db()
    filter_type = request.args.get('filter', 'upcoming')
    search_query = request.args.get('q', '')
    
    query = 'SELECT * FROM schedules WHERE 1=1'
    params = []
    
    if search_query:
        query += ' AND (activity LIKE ? OR location LIKE ? OR description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'])
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    if filter_type == 'today':
        query += ' AND date = ?'
        params.append(today)
    elif filter_type == 'week':
        # Simple week filter for SQLite
        query += " AND date >= date('now', 'localtime', 'weekday 0', '-7 days') AND date <= date('now', 'localtime', 'weekday 0')"
    elif filter_type == 'month':
        query += " AND strftime('%m', date) = strftime('%m', 'now', 'localtime') AND strftime('%Y', date) = strftime('%Y', 'now', 'localtime')"
    elif filter_type == 'upcoming':
        query += ' AND date >= ?'
        params.append(today)
        
    query += ' ORDER BY date ASC, time ASC'
    
    rows = db.execute(query, params).fetchall()
    schedules = [dict(row) for row in rows]
    
    # Process dates for display
    for s in schedules:
        try:
            dt = datetime.strptime(s['date'], '%Y-%m-%d')
            s['formatted_date'] = dt.strftime('%d %B %Y')
            s['day_name'] = dt.strftime('%A')
        except:
            s['formatted_date'] = s['date']
            s['day_name'] = '-'

    return render_template('schedule/list.html', 
                           schedules=schedules, 
                           filter=filter_type, 
                           search=search_query,
                           today=today)

@schedule_bp.route('/add', methods=['GET', 'POST'])
@admin_required
def add():
    if request.method == 'POST':
        date = request.form.get('date')
        time = request.form.get('time')
        activity = request.form.get('activity')
        location = request.form.get('location')
        category = request.form.get('category', 'Latihan')
        priority = request.form.get('priority', 'Normal')
        description = request.form.get('description')
        is_important = 1 if request.form.get('is_important') else 0
        
        db = get_db()
        db.execute('''
            INSERT INTO schedules (date, time, activity, location, category, priority, description, is_important) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date, time, activity, location, category, priority, description, is_important))
        db.commit()
        
        # Notify all users
        add_notification(None, 'Jadwal Baru Diterbitkan', f'{activity} pada {date}', 'info', url='/schedule', category='schedule')
        broadcast_push_notification('Jadwal Baru Diterbitkan', f'{activity} pada {date}', url='/schedule')
        
        flash('Jadwal berhasil ditambahkan!', 'success')
        return redirect(url_for('schedule.list'))
    return render_template('schedule/add.html')

@schedule_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit(id):
    db = get_db()
    schedule = db.execute('SELECT * FROM schedules WHERE id = ?', (id,)).fetchone()
    if not schedule:
        flash('Jadwal tidak ditemukan!', 'danger')
        return redirect(url_for('schedule.list'))
        
    if request.method == 'POST':
        date = request.form.get('date')
        time = request.form.get('time')
        activity = request.form.get('activity')
        location = request.form.get('location')
        category = request.form.get('category')
        status = request.form.get('status')
        description = request.form.get('description')
        is_important = 1 if request.form.get('is_important') else 0
        
        db.execute('''
            UPDATE schedules 
            SET date = ?, time = ?, activity = ?, location = ?, category = ?, status = ?, description = ?, is_important = ? 
            WHERE id = ?
        ''', (date, time, activity, location, category, status, description, is_important, id))
        db.commit()
        
        # Notify all users
        add_notification(None, 'Pembaruan Jadwal', f'Perubahan pada: {activity}', 'warning', url='/schedule', category='schedule')
        broadcast_push_notification('Pembaruan Jadwal', f'Perubahan pada: {activity}', url='/schedule')
        
        flash('Jadwal berhasil diperbarui.', 'success')
        return redirect(url_for('schedule.list'))
        
    return render_template('schedule/edit.html', s=dict(schedule))

@schedule_bp.route('/delete/<int:id>', methods=['POST'])
@admin_required
def delete(id):
    db = get_db()
    db.execute('DELETE FROM schedules WHERE id = ?', (id,))
    db.commit()
    flash('Jadwal telah dihapus.', 'warning')
    return redirect(url_for('schedule.list'))

@schedule_bp.route('/status/<int:id>/<string:status>', methods=['POST'])
@admin_required
def update_status(id, status):
    db = get_db()
    db.execute('UPDATE schedules SET status = ? WHERE id = ?', (status, id))
    db.commit()
    flash(f'Status jadwal diperbarui ke {status}.', 'success')
    return redirect(url_for('schedule.list'))
