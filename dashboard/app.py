from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, session
from functools import wraps
import sys
import os
import psutil
import threading
from datetime import datetime, timedelta
from collections import defaultdict

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from database import db_manager

app = Flask(__name__)

# Session security: use fixed secret key from environment
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    app.secret_key = os.urandom(32).hex()
    print(f"WARNING: No FLASK_SECRET_KEY set. Generated temporary key: {app.secret_key}")
    print("Set FLASK_SECRET_KEY environment variable for persistent sessions.")

app.permanent_session_lifetime = timedelta(minutes=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# CSRF Protection
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)
app.config['WTF_CSRF_CHECK_DEFAULT'] = False
app.config['WTF_CSRF_TIME_LIMIT'] = 3600

# Login rate limiting
login_attempts = defaultdict(list)
LOGIN_LOCKOUT_MINUTES = 15
LOGIN_MAX_ATTEMPTS = 5

def check_login_rate_limit(ip):
    now = datetime.now()
    login_attempts[ip] = [t for t in login_attempts[ip] if now - t < timedelta(minutes=LOGIN_LOCKOUT_MINUTES)]
    return len(login_attempts[ip]) >= LOGIN_MAX_ATTEMPTS

def record_login_attempt(ip):
    login_attempts[ip].append(datetime.now())

@app.before_request
def check_csrf():
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        if request.path in ('/login',):
            return
        csrf.protect()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------- API Key encryption helpers ----------
def save_encrypted_setting(key, value):
    encryption_key = os.environ.get('ENCRYPTION_KEY')
    if encryption_key and value:
        try:
            from cryptography.fernet import Fernet
            import base64
            cipher = Fernet(base64.urlsafe_b64encode(
                encryption_key.encode()[:32].ljust(32, b'0')
            ))
            encrypted = cipher.encrypt(value.encode()).decode()
            db_manager.update_setting(key, encrypted)
            return
        except Exception as e:
            print(f"Encryption failed for {key}, storing plaintext: {e}")
    db_manager.update_setting(key, value)

# ---------- LOGIN / LOGOUT ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        ip = request.remote_addr or 'unknown'
        if check_login_rate_limit(ip):
            return render_template('login.html',
                                   error="Too many failed attempts. Try again in 15 minutes.")

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        record_login_attempt(ip)

        if db_manager.verify_admin(username, password):
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            login_attempts[ip] = []
            print(f"Admin Login: {username}")
            return redirect(url_for('index'))
        else:
            error = "Wrong username or password!"

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    old_pass = request.form.get('old_password', '')
    new_pass = request.form.get('new_password', '')
    username = session.get('username', 'admin')

    if not db_manager.verify_admin(username, old_pass):
        return jsonify({"status": "error", "message": "Old password is wrong!"})
    if len(new_pass) < 6:
        return jsonify({"status": "error", "message": "New password must be at least 6 characters!"})

    db_manager.update_admin_password(username, new_pass)
    return jsonify({"status": "success", "message": "Password changed successfully!"})

@app.route('/')
@login_required
def index():
    status = db_manager.get_setting('bot_status', 'ON')
    total_deals = db_manager.get_total_deals_count()
    today_deals = db_manager.get_deals_today_count()
    recent_deals = db_manager.get_recent_deals(15)
    channels = db_manager.get_all_channels()
    categories = db_manager.get_all_categories()
    return render_template('index.html',
                           bot_status=status,
                           total_deals=total_deals,
                           today_deals=today_deals,
                           recent_deals=recent_deals,
                           channels_count=len(channels),
                           categories_count=len(categories))

@app.route('/settings')
@login_required
def settings():
    api_id = db_manager.get_setting('API_ID', '')
    api_hash = db_manager.get_setting('API_HASH', '')
    bot_token = db_manager.get_setting('BOT_TOKEN', '')
    extrape_affid = db_manager.get_setting('EXTRAPE_AFFID', '')
    extrape_param1 = db_manager.get_setting('EXTRAPE_PARAM1', '')
    flash_interval = db_manager.get_setting('FLASH_INTERVAL', '3')
    round_wait = db_manager.get_setting('ROUND_WAIT', '15')
    long_sleep = db_manager.get_setting('LONG_SLEEP', '60')
    keywords_per_round = db_manager.get_setting('KEYWORDS_PER_ROUND', '4')
    default_post_format = db_manager.get_setting('DEFAULT_POST_FORMAT', 'hot_deal')
    flash_post_format = db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot')
    price_screenshot = db_manager.normalize_price_screenshot_setting(
        db_manager.get_setting('PRICE_SCREENSHOT', 'ON')
    )
    min_buyers_count = db_manager.get_setting('MIN_BUYERS_COUNT', '1000')
    max_scrape_pages = db_manager.get_setting('MAX_SCRAPE_PAGES', '3')
    max_workers = db_manager.get_setting('MAX_WORKERS', '2')
    queue_delay_post = db_manager.get_setting('QUEUE_DELAY_POST', '15')
    allow_missing_buyers = db_manager.get_setting('ALLOW_MISSING_BUYERS', 'OFF')

    return render_template('settings.html',
                           api_id=api_id, api_hash=api_hash, bot_token=bot_token,
                           extrape_affid=extrape_affid, extrape_param1=extrape_param1,
                           flash_interval=flash_interval, round_wait=round_wait, long_sleep=long_sleep,
                           keywords_per_round=keywords_per_round,
                           default_post_format=default_post_format,
                           flash_post_format=flash_post_format,
                           price_screenshot=price_screenshot,
                           min_buyers_count=min_buyers_count,
                           max_scrape_pages=max_scrape_pages,
                           max_workers=max_workers,
                           queue_delay_post=queue_delay_post,
                           allow_missing_buyers=allow_missing_buyers)

@app.route('/save_settings', methods=['POST'])
@login_required
def save_settings():
    if request.method == 'POST':
        # Save sensitive API keys with encryption
        save_encrypted_setting('API_ID', request.form.get('api_id'))
        save_encrypted_setting('API_HASH', request.form.get('api_hash'))
        save_encrypted_setting('BOT_TOKEN', request.form.get('bot_token'))

        db_manager.update_setting('EXTRAPE_AFFID', request.form.get('extrape_affid'))
        db_manager.update_setting('EXTRAPE_PARAM1', request.form.get('extrape_param1'))
        db_manager.update_setting('FLASH_INTERVAL', request.form.get('flash_interval'))
        db_manager.update_setting('ROUND_WAIT', request.form.get('round_wait'))
        db_manager.update_setting('LONG_SLEEP', request.form.get('long_sleep'))
        db_manager.update_setting('KEYWORDS_PER_ROUND', request.form.get('keywords_per_round'))
        db_manager.update_setting('DEFAULT_POST_FORMAT', request.form.get('default_post_format', 'hot_deal'))
        db_manager.update_setting('FLASH_POST_FORMAT', request.form.get('flash_post_format', 'mega_loot'))
        price_ss = db_manager.normalize_price_screenshot_setting(
            request.form.get('price_screenshot', 'ON')
        )
        db_manager.update_setting('PRICE_SCREENSHOT', price_ss)
        db_manager.update_setting('MIN_BUYERS_COUNT', request.form.get('min_buyers_count', '1000'))
        db_manager.update_setting('MAX_SCRAPE_PAGES', request.form.get('max_scrape_pages', '3'))
        db_manager.update_setting('MAX_WORKERS', request.form.get('max_workers', '2'))
        db_manager.update_setting('QUEUE_DELAY_POST', request.form.get('queue_delay_post', '15'))
        allow_mb = 'ON' if request.form.get('allow_missing_buyers') == 'ON' else 'OFF'
        db_manager.update_setting('ALLOW_MISSING_BUYERS', allow_mb)
        print(f"Settings saved")
        return redirect(url_for('settings'))

@app.route('/channels')
@login_required
def channels():
    all_channels = db_manager.get_all_channels()
    return render_template('channels.html', channels=all_channels)

@app.route('/add_channel', methods=['POST'])
@login_required
def add_channel():
    channel_id = request.form.get('channel_id')
    channel_name = request.form.get('channel_name')
    if channel_id and channel_name:
        db_manager.add_channel(channel_id, channel_name)
    return redirect(url_for('channels'))

@app.route('/delete_channel/<channel_id>')
@login_required
def delete_channel(channel_id):
    db_manager.delete_channel(channel_id)
    return redirect(url_for('channels'))

@app.route('/categories')
@login_required
def categories():
    all_categories = db_manager.get_all_categories()
    return render_template('categories.html', categories=all_categories)

@app.route('/add_category', methods=['POST'])
@login_required
def add_category():
    name = request.form.get('name')
    keywords = request.form.get('keywords')
    min_discount = request.form.get('min_discount')
    priority = request.form.get('priority', 'MEDIUM')
    post_format = request.form.get('post_format', 'default')
    if name and keywords and min_discount:
        db_manager.add_category(name, keywords, int(min_discount), priority, post_format)
    return redirect(url_for('categories'))

@app.route('/delete_category/<cat_id>')
@login_required
def delete_category(cat_id):
    db_manager.delete_category(cat_id)
    return redirect(url_for('categories'))

@app.route('/edit_category/<int:cat_id>', methods=['POST'])
@login_required
def edit_category(cat_id):
    name = request.form.get('name')
    keywords = request.form.get('keywords')
    min_discount = request.form.get('min_discount')
    priority = request.form.get('priority', 'MEDIUM')
    post_format = request.form.get('post_format', 'default')
    if name and keywords and min_discount:
        db_manager.update_category(cat_id, name, keywords, int(min_discount), priority, post_format)
    return redirect(url_for('categories'))

@app.route('/flash_deals')
@login_required
def flash_deals():
    all_flash_keywords = db_manager.get_all_flash_keywords()
    return render_template('flash_deals.html', flash_keywords=all_flash_keywords)

@app.route('/add_flash', methods=['POST'])
@login_required
def add_flash():
    keyword = request.form.get('keyword')
    min_discount = request.form.get('min_discount')
    if keyword and min_discount:
        db_manager.add_flash_keyword(keyword.strip().lower(), int(min_discount))
    return redirect(url_for('flash_deals'))

@app.route('/delete_flash/<int:keyword_id>')
@login_required
def delete_flash(keyword_id):
    db_manager.delete_flash_keyword(keyword_id)
    return redirect(url_for('flash_deals'))

@app.route('/edit_flash/<int:keyword_id>', methods=['POST'])
@login_required
def edit_flash(keyword_id):
    keyword = request.form.get('keyword')
    min_discount = request.form.get('min_discount')
    if keyword and min_discount:
        db_manager.update_flash_keyword(keyword_id, keyword.strip().lower(), int(min_discount))
    return redirect(url_for('flash_deals'))

@app.route('/instant_post')
@login_required
def instant_post():
    return render_template('instant_post.html')

@app.route('/instant_post_send', methods=['POST'])
@login_required
def instant_post_send():
    product_url = request.form.get('product_url', '').strip()
    post_format = request.form.get('post_format', 'default')

    if not product_url:
        return jsonify({"status": "error", "message": "Link is empty! Paste a Flipkart link."})
    if 'flipkart.com' not in product_url and 'fkrt.it' not in product_url:
        return jsonify({"status": "error", "message": "This is not a Flipkart link! Only Flipkart links accepted."})

    def process_instant_post(url, chosen_format):
        try:
            from scraper.flipkart import scrape_single_product
            from telegram.post_format import build_deal_message, resolve_post_format
            from telegram.bot import send_telegram_deal_post
            from telegram.deal_media import post_deal_message, cleanup_deal_media
            from config import EXTRAPE_AFFID, EXTRAPE_PARAM1
            import requests as req

            print(f"\n[INSTANT POST] Processing: {url[:60]}...")
            deal = scrape_single_product(url)
            if not deal:
                print("[INSTANT POST] Product scrape failed.")
                return

            print("[INSTANT POST] Generating affiliate link...")
            affiliate_link = url
            try:
                from userbot.extrape_agent import get_sync_link
                agent_link = get_sync_link(url)
                if agent_link and agent_link != url:
                    affiliate_link = agent_link
                else:
                    raise Exception("Agent returned same link")
            except Exception:
                try:
                    if not EXTRAPE_AFFID:
                        raise ValueError("EXTRAPE_AFFID is not configured")
                    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
                    parts = urlsplit(url)
                    query = dict(parse_qsl(parts.query, keep_blank_values=True))
                    query["affid"] = EXTRAPE_AFFID
                    query["affExtParam1"] = EXTRAPE_PARAM1
                    affiliate_link = urlunsplit(
                        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
                    )
                except Exception:
                    pass

            fmt = resolve_post_format(
                is_flash=False,
                category_format=chosen_format,
                default_format=db_manager.get_setting('DEFAULT_POST_FORMAT', 'hot_deal'),
                flash_format=db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot'),
            )
            message = build_deal_message(deal, affiliate_link, fmt)

            try:
                channels = db_manager.get_all_channels()
            except Exception:
                channels = []
            if not channels:
                print("[INSTANT POST] No channels configured!")
                return

            sent_count = 0
            try:
                for channel in channels:
                    try:
                        result = post_deal_message(
                            send_telegram_deal_post, channel[0], message, deal
                        )
                        if result:
                            sent_count += 1
                    except Exception as e:
                        print(f"[INSTANT POST] Channel {channel[0]} send failed: {e}")

                if sent_count:
                    try:
                        db_manager.save_deal(
                            title=deal['title'],
                            original_link=url,
                            affiliate_link=affiliate_link,
                            category="INSTANT POST"
                        )
                    except Exception:
                        pass
                    print(f"[INSTANT POST] Deal posted: {deal['title'][:40]}...")
                else:
                    print("[INSTANT POST] Two-photo delivery failed; deal not marked sent.")
            finally:
                cleanup_deal_media(deal)

        except Exception as e:
            print(f"[INSTANT POST] Error: {e}")

    thread = threading.Thread(target=process_instant_post, args=(product_url, post_format), daemon=True)
    thread.start()
    return jsonify({"status": "success", "message": "Processing started! Will post to Telegram in 10-15 seconds."})

@app.route('/live_console')
@login_required
def live_console():
    return render_template('console.html')

@app.route('/get_logs')
@login_required
def get_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    if not os.path.exists(log_file_path):
        return "Bot is starting... Logs not yet available."
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return "".join(lines[-100:])
    except Exception as e:
        return f"Error reading logs: {str(e)}"

@app.route('/system_stats')
@login_required
def system_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    mem_used_mb = int(mem.used / (1024 * 1024))
    return jsonify({'cpu': cpu, 'mem': mem_used_mb})

@app.route('/export_logs')
@login_required
def export_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    if os.path.exists(log_file_path):
        return send_file(log_file_path, as_attachment=True, download_name='Deal_Hunter_Logs.txt')
    return "Log file not yet created.", 404

@app.route('/restart_bot', methods=['POST'])
@login_required
def restart_bot():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write("\n[SYSTEM] Restart Command Received!\n")
    return jsonify({"status": "success"})

@app.route('/clear_logs', methods=['POST'])
@login_required
def clear_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    try:
        with open(log_file_path, 'w', encoding='utf-8') as f:
            f.write("")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/toggle_bot', methods=['POST'])
@login_required
def toggle_bot():
    current = db_manager.get_setting('bot_status', 'ON')
    new_status = 'OFF' if current == 'ON' else 'ON'
    db_manager.update_setting('bot_status', new_status)
    print(f"BOT STATUS CHANGED TO: {new_status}")
    return redirect(url_for('index'))

@app.route('/health')
def health():
    """Health check endpoint for Docker/load balancers."""
    return jsonify({
        "status": "ok",
        "bot_status": db_manager.get_setting('bot_status', 'ON'),
        "db_connected": True,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    db_manager.init_db()
    app.run(debug=True, port=5000)
