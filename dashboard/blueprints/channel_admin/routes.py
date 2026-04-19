"""
dashboard/blueprints/channel_admin/routes.py
=============================================
Channel Admin Panel — Per-Channel Control

URL structure:
  /channel/<slug>/login         → login page
  /channel/<slug>/logout        → logout
  /channel/<slug>/              → dashboard
  /channel/<slug>/categories    → manage categories
  /channel/<slug>/flash-deals   → manage flash deals
  /channel/<slug>/deals         → sent deals history

Session keys stored:
  ca_admin_id_<slug>      → admin's DB id
  ca_token_<slug>         → session token (verified against DB)
  ca_channel_id_<slug>    → channel id

Each key is slug-scoped so multiple channel panels can be
open in the same browser without conflicts.
"""

import os
import sys
import time
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import db_manager

# ── Blueprint ────────────────────────────────────────────────────────────────
channel_admin_bp = Blueprint(
    'channel_admin',
    __name__,
    template_folder='../../templates/channel_admin',
    url_prefix='/channel'
)


# ═══════════════════════════════════════════════════════════════════════════
# SESSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _skey(slug: str, key: str) -> str:
    """Namespaced session key to avoid cross-slug collisions."""
    return f"ca_{key}_{slug}"


def _is_logged_in(slug: str) -> bool:
    admin_id = session.get(_skey(slug, 'admin_id'))
    token    = session.get(_skey(slug, 'token'))
    if not admin_id or not token:
        return False
    return db_manager.verify_session_token(admin_id, token)


def _get_session_channel_id(slug: str) -> str | None:
    return session.get(_skey(slug, 'channel_id'))


def channel_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        slug = kwargs.get('slug', '')
        if not _is_logged_in(slug):
            return redirect(url_for('channel_admin.login', slug=slug))
        return f(*args, **kwargs)
    return decorated


def _clear_session(slug: str):
    for key in ('admin_id', 'token', 'channel_id', 'username'):
        session.pop(_skey(slug, key), None)


# ═══════════════════════════════════════════════════════════════════════════
# GUARD — slug must exist in DB before anything else
# ═══════════════════════════════════════════════════════════════════════════
def _slug_exists(slug: str) -> dict | None:
    return db_manager.get_admin_by_slug(slug)


# ═══════════════════════════════════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════════════════
@channel_admin_bp.route('/<slug>/login', methods=['GET', 'POST'])
def login(slug: str):
    # Unknown slug → 404-style redirect
    admin_row = _slug_exists(slug)
    if not admin_row:
        return render_template('error.html',
                               message='Panel not found.'), 404

    # Already logged in
    if _is_logged_in(slug):
        return redirect(url_for('channel_admin.panel_dashboard', slug=slug))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            error = 'Please enter username and password.'
        else:
            admin = db_manager.login_channel_admin(username, password)

            if admin and admin['panel_slug'] == slug:
                # Store slug-scoped session
                session[_skey(slug, 'admin_id')]  = admin['id']
                session[_skey(slug, 'token')]     = admin['session_token']
                session[_skey(slug, 'channel_id')]= admin['channel_id']
                session[_skey(slug, 'username')]  = admin['username']
                session.permanent = True
                return redirect(url_for('channel_admin.panel_dashboard', slug=slug))
            else:
                time.sleep(1)  # brute-force slowdown
                error = 'Invalid credentials. Contact your super admin.'

    return render_template('login.html',
                           slug=slug,
                           panel_name=admin_row.get('panel_slug', slug).replace('-', ' ').title(),
                           error=error)


@channel_admin_bp.route('/<slug>/logout')
def logout(slug: str):
    admin_id = session.get(_skey(slug, 'admin_id'))
    if admin_id:
        db_manager.logout_channel_admin(admin_id)  # invalidate token in DB
    _clear_session(slug)
    return redirect(url_for('channel_admin.login', slug=slug))


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
@channel_admin_bp.route('/<slug>/')
@channel_admin_bp.route('/<slug>/dashboard')
@channel_login_required
def panel_dashboard(slug: str):
    channel_id = _get_session_channel_id(slug)
    channel    = db_manager.get_channel_by_id(channel_id)
    categories = db_manager.get_categories_by_channel(channel_id)
    flash_kws  = db_manager.get_flash_keywords_by_channel(channel_id)
    recent     = db_manager.get_recent_deals(limit=10, channel_id=channel_id)
    total      = db_manager.get_total_deals_count(channel_id=channel_id)

    stats = {
        'category_count' : len(categories),
        'flash_kw_count' : len(flash_kws),
        'deals_sent'     : total,
    }

    return render_template('index.html',
                           slug=slug,
                           channel=channel,
                           stats=stats,
                           recent_deals=recent,
                           username=session.get(_skey(slug, 'username')))


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════
@channel_admin_bp.route('/<slug>/categories', methods=['GET'])
@channel_login_required
def categories(slug: str):
    channel_id = _get_session_channel_id(slug)
    channel    = db_manager.get_channel_by_id(channel_id)
    cats       = db_manager.get_categories_by_channel(channel_id)
    return render_template('categories.html',
                           slug=slug,
                           channel=channel,
                           categories=cats,
                           username=session.get(_skey(slug, 'username')))


@channel_admin_bp.route('/<slug>/categories/add', methods=['POST'])
@channel_login_required
def add_category(slug: str):
    channel_id   = _get_session_channel_id(slug)
    name         = request.form.get('name', '').strip()
    keywords     = request.form.get('keywords', '').strip()
    min_discount = request.form.get('min_discount', '40').strip()

    if not name or not keywords:
        flash('Name and keywords are required.', 'error')
        return redirect(url_for('channel_admin.categories', slug=slug))

    try:
        min_discount = int(min_discount)
        if not (1 <= min_discount <= 99):
            raise ValueError
    except ValueError:
        flash('Discount must be a number between 1 and 99.', 'error')
        return redirect(url_for('channel_admin.categories', slug=slug))

    db_manager.add_category(name, keywords, min_discount, channel_id)
    flash(f'Category "{name}" added.', 'success')
    return redirect(url_for('channel_admin.categories', slug=slug))


@channel_admin_bp.route('/<slug>/categories/delete', methods=['POST'])
@channel_login_required
def delete_category(slug: str):
    channel_id = _get_session_channel_id(slug)
    cat_id     = request.form.get('cat_id', type=int)
    if cat_id:
        db_manager.delete_category(cat_id, channel_id=channel_id)
        flash('Category deleted.', 'success')
    return redirect(url_for('channel_admin.categories', slug=slug))


@channel_admin_bp.route('/<slug>/categories/edit', methods=['POST'])
@channel_login_required
def edit_category(slug: str):
    channel_id   = _get_session_channel_id(slug)
    cat_id       = request.form.get('cat_id', type=int)
    name         = request.form.get('name', '').strip()
    keywords     = request.form.get('keywords', '').strip()
    min_discount = request.form.get('min_discount', '40').strip()

    if not cat_id or not name or not keywords:
        flash('All fields required.', 'error')
        return redirect(url_for('channel_admin.categories', slug=slug))

    try:
        min_discount = int(min_discount)
    except ValueError:
        flash('Invalid discount value.', 'error')
        return redirect(url_for('channel_admin.categories', slug=slug))

    db_manager.update_category(cat_id, name, keywords, min_discount, channel_id=channel_id)
    flash('Category updated.', 'success')
    return redirect(url_for('channel_admin.categories', slug=slug))


# ═══════════════════════════════════════════════════════════════════════════
# FLASH DEALS
# ═══════════════════════════════════════════════════════════════════════════
@channel_admin_bp.route('/<slug>/flash-deals', methods=['GET'])
@channel_login_required
def flash_deals(slug: str):
    channel_id = _get_session_channel_id(slug)
    keywords   = db_manager.get_flash_keywords_by_channel(channel_id)
    return render_template('flash_deals.html',
                           slug=slug,
                           keywords=keywords,
                           username=session.get(_skey(slug, 'username')))


@channel_admin_bp.route('/<slug>/flash-deals/add', methods=['POST'])
@channel_login_required
def add_flash_keyword(slug: str):
    channel_id   = _get_session_channel_id(slug)
    keyword      = request.form.get('keyword', '').strip().lower()
    min_discount = request.form.get('min_discount', '60').strip()

    if not keyword:
        flash('Keyword is required.', 'error')
        return redirect(url_for('channel_admin.flash_deals', slug=slug))

    try:
        min_discount = int(min_discount)
        if not (1 <= min_discount <= 99):
            raise ValueError
    except ValueError:
        flash('Discount must be between 1 and 99.', 'error')
        return redirect(url_for('channel_admin.flash_deals', slug=slug))

    db_manager.add_flash_keyword(keyword, min_discount, channel_id)
    flash(f'Flash keyword "{keyword}" added.', 'success')
    return redirect(url_for('channel_admin.flash_deals', slug=slug))


@channel_admin_bp.route('/<slug>/flash-deals/delete', methods=['POST'])
@channel_login_required
def delete_flash_keyword(slug: str):
    channel_id = _get_session_channel_id(slug)
    kw_id      = request.form.get('kw_id', type=int)
    if kw_id:
        db_manager.delete_flash_keyword(kw_id, channel_id=channel_id)
        flash('Flash keyword deleted.', 'success')
    return redirect(url_for('channel_admin.flash_deals', slug=slug))


# ═══════════════════════════════════════════════════════════════════════════
# DEALS HISTORY
# ═══════════════════════════════════════════════════════════════════════════
@channel_admin_bp.route('/<slug>/deals')
@channel_login_required
def deals_history(slug: str):
    channel_id = _get_session_channel_id(slug)
    deals      = db_manager.get_recent_deals(limit=100, channel_id=channel_id)
    return render_template('deals.html',
                           slug=slug,
                           deals=deals,
                           username=session.get(_skey(slug, 'username')))