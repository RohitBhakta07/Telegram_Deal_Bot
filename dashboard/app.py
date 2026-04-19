"""
dashboard/app.py
================
Main Flask Application Entry Point

URL Map:
  /                          → Super Admin Panel  (login required)
  /login                     → Super Admin Login
  /logout                    → Super Admin Logout
  /channels                  → Manage channels
  /admins                    → Manage channel admins
  /overview                  → Per-channel stats
  /live_console              → Bot log stream
  /settings                  → Config viewer
  /log_stream                → SSE log endpoint

  /channel/<slug>/login      → Channel Admin Login
  /channel/<slug>/           → Channel Admin Dashboard
  /channel/<slug>/categories → Manage categories
  /channel/<slug>/flash-deals→ Manage flash keywords
  /channel/<slug>/deals      → Sent deals history
"""

import os
import sys
from datetime import timedelta

# ── Path setup (MUST be before blueprint imports) ────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, render_template
from dashboard.blueprints.super_admin.routes  import super_admin_bp
from dashboard.blueprints.channel_admin.routes import channel_admin_bp

from database import db_manager

# ── App factory ─────────────────────────────────────────────────────────────
def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, 'templates'),
        static_folder=os.path.join(BASE_DIR, 'static')
    )

    # ── Security config ──────────────────────────────────────────────────────
    # IMPORTANT: Change SECRET_KEY before production deployment
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-this-in-production-!!xyz9#$')
    app.config['SESSION_COOKIE_HTTPONLY'] = True   # JS can't read session cookie
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

    # Super Admin password — set via env variable in production
    app.config['SUPER_ADMIN_PASSWORD'] = os.environ.get('SUPER_ADMIN_PASSWORD', 'admin@123')

    # ── Init DB ──────────────────────────────────────────────────────────────
    db_manager.init_db()

    # ── Register blueprints ──────────────────────────────────────────────────
    from dashboard.blueprints.super_admin.routes  import super_admin_bp
    from dashboard.blueprints.channel_admin.routes import channel_admin_bp

    app.register_blueprint(super_admin_bp)    # prefix: /
    app.register_blueprint(channel_admin_bp)  # prefix: /channel

    # ── Error handlers ───────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template('super_admin/error.html',
                               code=404,
                               message='Page not found.'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('super_admin/error.html',
                               code=500,
                               message='Internal server error.'), 500

    return app


# ── Run directly ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = create_app()
    app.run(
        debug=True,
        port=5000,
        host='0.0.0.0',     # accessible on local network too
        use_reloader=True,
        threaded=True       # needed for SSE log stream
    )