"""
dashboard/blueprints/super_admin/routes.py
==========================================
Super Admin Panel — Full Control
Routes:
  GET  /                        → dashboard (stats)
  GET  /channels                → list channels + admins
  POST /channels/add            → add channel
  POST /channels/delete         → delete channel
  POST /channels/toggle         → toggle active/inactive

  GET  /admins                  → list all channel admins
  POST /admins/create           → create channel admin
  POST /admins/delete           → delete channel admin
  POST /admins/toggle           → enable / disable admin
  POST /admins/reset-password   → reset admin password

  GET  /overview                → per-channel stats table
  GET  /live_console            → live bot log stream
  GET  /log_stream              → SSE endpoint for log
  GET  /settings                → settings page
  POST /settings/update         → update settings
  GET  /login                   → login page
  POST /login                   → process login
  GET  /logout                  → logout
"""

import os
import json
import time
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, Response, current_app
)

# ── import db_manager from project root ─────────────────────────────────────
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import db_manager

# ── Blueprint ────────────────────────────────────────────────────────────────
super_admin_bp = Blueprint(
    'super_admin',
    __name__,
    template_folder='../../templates/super_admin',
    url_prefix='/'
)

SUPER_ADMIN_SESSION_KEY = 'super_admin_logged_in'


# ═══════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get(SUPER_ADMIN_SESSION_KEY):
            return redirect(url_for('super_admin.login'))
        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get(SUPER_ADMIN_SESSION_KEY):
        return redirect(url_for('super_admin.dashboard'))

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        admin_password = current_app.config.get('SUPER_ADMIN_PASSWORD', 'admin123')

        if password == admin_password:
            session[SUPER_ADMIN_SESSION_KEY] = True
            session.permanent = True
            return redirect(url_for('super_admin.dashboard'))
        else:
            error = 'Invalid password. Try again.'
            time.sleep(1)  # basic brute-force slowdown

    return render_template('login.html', error=error)


@super_admin_bp.route('/logout')
def logout():
    session.pop(SUPER_ADMIN_SESSION_KEY, None)
    return redirect(url_for('super_admin.login'))


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/')
@login_required
def dashboard():
    stats      = db_manager.get_super_admin_stats()
    per_channel = db_manager.get_per_channel_stats()
    return render_template('index.html', stats=stats, per_channel=per_channel)


# ═══════════════════════════════════════════════════════════════════════════
# CHANNELS
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/channels')
@login_required
def channels():
    all_channels = db_manager.get_all_channels()
    all_admins   = db_manager.get_all_admins()

    # attach admin info to each channel for easy display
    admin_map = {a['channel_id']: a for a in all_admins}
    for ch in all_channels:
        ch['admin'] = admin_map.get(ch['channel_id'])

    return render_template('channels.html', channels=all_channels)


@super_admin_bp.route('/channels/add', methods=['POST'])
@login_required
def add_channel():
    channel_id   = request.form.get('channel_id', '').strip()
    channel_name = request.form.get('channel_name', '').strip()

    if not channel_id or not channel_name:
        flash('Channel ID and Name are required.', 'error')
        return redirect(url_for('super_admin.channels'))

    if not channel_id.startswith('@') and not channel_id.lstrip('-').isdigit():
        flash('Channel ID must start with @ (e.g. @mychannel) or be a numeric ID.', 'error')
        return redirect(url_for('super_admin.channels'))

    success = db_manager.add_channel(channel_id, channel_name)
    if success:
        flash(f'Channel "{channel_name}" added successfully.', 'success')
    else:
        flash('Channel ID already exists.', 'error')

    return redirect(url_for('super_admin.channels'))


@super_admin_bp.route('/channels/delete', methods=['POST'])
@login_required
def delete_channel():
    channel_id = request.form.get('channel_id', '').strip()
    if channel_id:
        db_manager.delete_channel(channel_id)
        flash('Channel and all associated data deleted.', 'success')
    return redirect(url_for('super_admin.channels'))


@super_admin_bp.route('/channels/toggle', methods=['POST'])
@login_required
def toggle_channel():
    channel_id = request.form.get('channel_id', '').strip()
    if channel_id:
        db_manager.toggle_channel_active(channel_id)
    return redirect(url_for('super_admin.channels'))


# ═══════════════════════════════════════════════════════════════════════════
# CHANNEL ADMINS
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/admins')
@login_required
def admins():
    all_admins   = db_manager.get_all_admins()
    all_channels = db_manager.get_all_channels()
    return render_template('admins.html', admins=all_admins, channels=all_channels)


@super_admin_bp.route('/admins/create', methods=['POST'])
@login_required
def create_admin():
    channel_id = request.form.get('channel_id', '').strip()
    username   = request.form.get('username', '').strip()
    password   = request.form.get('password', '').strip()
    panel_slug = request.form.get('panel_slug', '').strip()

    if not all([channel_id, username, password, panel_slug]):
        flash('All fields are required.', 'error')
        return redirect(url_for('super_admin.admins'))

    ok, msg = db_manager.create_channel_admin(channel_id, username, password, panel_slug)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('super_admin.admins'))


@super_admin_bp.route('/admins/delete', methods=['POST'])
@login_required
def delete_admin():
    admin_id = request.form.get('admin_id', type=int)
    if admin_id:
        db_manager.delete_channel_admin(admin_id)
        flash('Admin account deleted.', 'success')
    return redirect(url_for('super_admin.admins'))


@super_admin_bp.route('/admins/toggle', methods=['POST'])
@login_required
def toggle_admin():
    admin_id = request.form.get('admin_id', type=int)
    if admin_id:
        db_manager.toggle_admin_active(admin_id)
    return redirect(url_for('super_admin.admins'))


@super_admin_bp.route('/admins/reset-password', methods=['POST'])
@login_required
def reset_password():
    admin_id     = request.form.get('admin_id', type=int)
    new_password = request.form.get('new_password', '').strip()

    if not admin_id or not new_password:
        flash('Admin ID and new password are required.', 'error')
        return redirect(url_for('super_admin.admins'))

    ok, msg = db_manager.update_admin_password(admin_id, new_password)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('super_admin.admins'))


# ═══════════════════════════════════════════════════════════════════════════
# OVERVIEW  (per-channel stats table)
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/overview')
@login_required
def overview():
    per_channel = db_manager.get_per_channel_stats()
    return render_template('overview.html', per_channel=per_channel)


# ═══════════════════════════════════════════════════════════════════════════
# LIVE CONSOLE
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/live_console')
@login_required
def live_console():
    return render_template('console.html')


@super_admin_bp.route('/log_stream')
@login_required
def log_stream():
    """
    Server-Sent Events endpoint.
    Streams new lines from bot.log to the browser in real time.
    """
    log_path = os.path.join(PROJECT_ROOT, 'bot.log')

    def generate():
        # start from the last 50 lines so console isn't empty on load
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                last_lines = lines[-50:] if len(lines) > 50 else lines
                for line in last_lines:
                    yield f"data: {json.dumps(line.rstrip())}\n\n"
        except FileNotFoundError:
            yield f"data: {json.dumps('bot.log not found. Start main.py first.')}\n\n"

        # stream new lines
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(0, 2)  # go to end of file
                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {json.dumps(line.rstrip())}\n\n"
                    else:
                        time.sleep(0.5)
        except Exception:
            return

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════
@super_admin_bp.route('/settings')
@login_required
def settings():
    config_path = os.path.join(PROJECT_ROOT, 'config.py')
    config_vars = {}
    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, _, val = line.partition('=')
                    config_vars[key.strip()] = val.strip().strip('"').strip("'")
    except Exception:
        pass
    return render_template('settings.html', config_vars=config_vars)