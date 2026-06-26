from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, session, abort
from functools import wraps
import sys
import os
import psutil
import threading
import time as time_module
import secrets
import logging

# 🛡️ SECURITY: Set up audit log for auth events
auth_logger = logging.getLogger('dashboard_auth')
auth_logger.setLevel(logging.INFO)
_auth_handler = logging.FileHandler(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth_audit.log'),
    encoding='utf-8'
)
_auth_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
auth_logger.addHandler(_auth_handler)
auth_logger.propagate = False

# 🛡️ SECURITY: In-memory rate limiter (login brute-force protection)
_rate_limit_store = {}  # {ip: [timestamp1, timestamp2, ...]}

def _is_rate_limited(ip_key, max_attempts=5, window_seconds=60):
    """Return True if IP has exceeded max login attempts in the time window."""
    now = time_module.time()
    if ip_key not in _rate_limit_store:
        _rate_limit_store[ip_key] = []
    timestamps = _rate_limit_store[ip_key]
    timestamps[:] = [t for t in timestamps if now - t < window_seconds]
    if len(timestamps) >= max_attempts:
        return True
    timestamps.append(now)
    return False

# 🛡️ SECURITY: CSRF token management
def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def csrf_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'POST':
            token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
            stored = session.get('csrf_token')
            if not stored or not token or not secrets.compare_digest(stored, token):
                auth_logger.warning(f"CSRF violation attempt from {request.remote_addr}")
                return jsonify({"status": "error", "message": "CSRF validation failed. Please refresh and try again."}), 403
        return f(*args, **kwargs)
    return decorated

# Database file path setup
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir) 
sys.path.append(parent_dir)

from database import db_manager

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
app.permanent_session_lifetime = __import__('datetime').timedelta(minutes=30)
# 🛡️ SECURITY: Session cookie hardening
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# ⚠️ Set SESSION_COOKIE_SECURE=True if using HTTPS (requires SSL certificate)

# 🛡️ SECURITY: Inject CSRF token into all templates
@app.context_processor
def inject_csrf():
    return dict(csrf_token=generate_csrf_token)

# 🔒 LOGIN REQUIRED DECORATOR — har protected route ke upar lagega
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        # 🛡️ SECURITY: Enforce session timeout (max 30 min inactivity)
        last_time = session.get('last_activity')
        now = time_module.time()
        if last_time and (now - last_time) > 1800:
            session.clear()
            return redirect(url_for('login'))
        session['last_activity'] = now
        return f(*args, **kwargs)
    return decorated_function

# 🔒 LOGIN / LOGOUT ROUTES
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        # 🛡️ SECURITY: Rate limiting by IP
        client_ip = request.remote_addr or 'unknown'
        if _is_rate_limited(f"login:{client_ip}"):
            auth_logger.warning(f"Rate limit hit for {client_ip}")
            error = "❌ Too many attempts. Please wait 60 seconds."
            return render_template('login.html', error=error)
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if db_manager.verify_admin(username, password):
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            session['login_time'] = time_module.time()
            # Regenerate CSRF token on login
            session['csrf_token'] = secrets.token_hex(32)
            auth_logger.info(f"Successful login: {username} from {client_ip}")
            print(f"🔒 Admin Login: {username}")
            return redirect(url_for('index'))
        else:
            auth_logger.warning(f"Failed login attempt: user='{username}' from {client_ip}")
            error = "❌ Wrong Username ya Password!"
    
    session['csrf_token'] = generate_csrf_token()
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/health')
def health():
    """🛡️ Monitoring endpoint — returns bot health status without auth."""
    db_ok = False
    try:
        db_manager.get_setting('bot_status')
        db_ok = True
    except Exception:
        pass
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "timestamp": time_module.time(),
    })

@app.route('/change_password', methods=['POST'])
@login_required
@csrf_required
def change_password():
    old_pass = request.form.get('old_password', '')
    new_pass = request.form.get('new_password', '')
    
    username = session.get('username', 'admin')
    
    if not db_manager.verify_admin(username, old_pass):
        return jsonify({"status": "error", "message": "❌ Old Password Wrong!"})
    
    if len(new_pass) < 4:
        return jsonify({"status": "error", "message": "❌ new password at least 4 characters !"})
    
    db_manager.update_admin_password(username, new_pass)
    return jsonify({"status": "success", "message": "✅ Password change successfully!"})

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

# 2. Settings Page
@app.route('/settings')
@login_required
def settings():
    api_id = db_manager.get_setting('API_ID', '')
    api_hash = db_manager.get_setting('API_HASH', '')
    bot_token = db_manager.get_setting('BOT_TOKEN', '')
    extrape_affid = db_manager.get_setting('EXTRAPE_AFFID', '')
    extrape_param1 = db_manager.get_setting('EXTRAPE_PARAM1', '')
    # ⚡ Bot Speed & Timing Settings (Defaults ke sath)
    flash_interval = db_manager.get_setting('FLASH_INTERVAL', '3')
    round_wait = db_manager.get_setting('ROUND_WAIT', '15')
    long_sleep = db_manager.get_setting('LONG_SLEEP', '60')
    # 🚀 Keywords Per Round
    keywords_per_round = db_manager.get_setting('KEYWORDS_PER_ROUND', '4')
    default_post_format = db_manager.get_setting('DEFAULT_POST_FORMAT', 'hot_deal')
    flash_post_format = db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot')
    price_screenshot = db_manager.normalize_price_screenshot_setting(
        db_manager.get_setting('PRICE_SCREENSHOT', 'OFF')
    )
    # 🚀 V2: Priority Queue Architecture Settings
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
@csrf_required
def save_settings():
    if request.method == 'POST':
        db_manager.update_setting('API_ID', request.form.get('api_id'))
        db_manager.update_setting('API_HASH', request.form.get('api_hash'))
        db_manager.update_setting('BOT_TOKEN', request.form.get('bot_token'))
        db_manager.update_setting('EXTRAPE_AFFID', request.form.get('extrape_affid'))
        db_manager.update_setting('EXTRAPE_PARAM1', request.form.get('extrape_param1'))
        # Save Speed Settings
        db_manager.update_setting('FLASH_INTERVAL', request.form.get('flash_interval'))
        db_manager.update_setting('ROUND_WAIT', request.form.get('round_wait'))
        db_manager.update_setting('LONG_SLEEP', request.form.get('long_sleep'))
        # 🚀 Keywords Per Round
        db_manager.update_setting('KEYWORDS_PER_ROUND', request.form.get('keywords_per_round'))
        db_manager.update_setting('DEFAULT_POST_FORMAT', request.form.get('default_post_format', 'hot_deal'))
        db_manager.update_setting('FLASH_POST_FORMAT', request.form.get('flash_post_format', 'mega_loot'))
        price_ss = db_manager.normalize_price_screenshot_setting(
            request.form.get('price_screenshot', 'OFF')
        )
        db_manager.update_setting('PRICE_SCREENSHOT', price_ss)
        # 🚀 V2: Priority Queue Architecture Settings
        db_manager.update_setting('MIN_BUYERS_COUNT', request.form.get('min_buyers_count', '1000'))
        db_manager.update_setting('MAX_SCRAPE_PAGES', request.form.get('max_scrape_pages', '3'))
        db_manager.update_setting('MAX_WORKERS', request.form.get('max_workers', '2'))
        db_manager.update_setting('QUEUE_DELAY_POST', request.form.get('queue_delay_post', '15'))
        allow_mb = 'ON' if request.form.get('allow_missing_buyers') == 'ON' else 'OFF'
        db_manager.update_setting('ALLOW_MISSING_BUYERS', allow_mb)
        print(f"💾 V2 Settings saved: MinBuyers={request.form.get('min_buyers_count')}, Workers={request.form.get('max_workers')}")

        return redirect(url_for('settings'))

# 3. Channels Page 
@app.route('/channels')
@login_required
def channels():
    all_channels = db_manager.get_all_channels()
    return render_template('channels.html', channels=all_channels)

@app.route('/add_channel', methods=['POST'])
@login_required
@csrf_required
def add_channel():
    channel_id = request.form.get('channel_id')
    channel_name = request.form.get('channel_name')
    if channel_id and channel_name:
        db_manager.add_channel(channel_id, channel_name)
    return redirect(url_for('channels'))

@app.route('/delete_channel/<channel_id>', methods=['GET', 'POST'])
@login_required
def delete_channel(channel_id):
    # 🛡️ SECURITY: Validate channel_id is alphanumeric + dash
    if not channel_id or any(c not in '-0123456789' for c in channel_id if c != '-'):
        return jsonify({"status": "error", "message": "Invalid channel ID"}), 400
    # 🛡️ SECURITY: CSRF check for POST; for GET links validate via query param token
    if request.method == 'POST':
        token = request.form.get('csrf_token')
    else:
        token = request.args.get('csrf_token')
    stored = session.get('csrf_token')
    if not stored or not token or not secrets.compare_digest(stored, token):
        auth_logger.warning(f"CSRF violation on delete_channel from {request.remote_addr}")
        return jsonify({"status": "error", "message": "CSRF validation failed"}), 403
    db_manager.delete_channel(channel_id)
    return redirect(url_for('channels'))

# ==========================================
# 4. CATEGORIES MANAGEMENT 
# ==========================================
@app.route('/categories')
@login_required
def categories():
    all_categories = db_manager.get_all_categories()
    return render_template('categories.html', categories=all_categories)

@app.route('/add_category', methods=['POST'])
@login_required
@csrf_required
def add_category():
    name = request.form.get('name')
    keywords = request.form.get('keywords') 
    min_discount = request.form.get('min_discount')
    priority = request.form.get('priority', 'MEDIUM')
    post_format = request.form.get('post_format', 'default')
    if name and keywords and min_discount:
        db_manager.add_category(name, keywords, int(min_discount), priority, post_format)
    return redirect(url_for('categories'))

@app.route('/delete_category/<cat_id>', methods=['GET', 'POST'])
@login_required
def delete_category(cat_id):
    # 🛡️ SECURITY: CSRF check for GET-based delete
    if request.method == 'POST':
        token = request.form.get('csrf_token')
    else:
        token = request.args.get('csrf_token')
    stored = session.get('csrf_token')
    if not stored or not token or not secrets.compare_digest(stored, token):
        auth_logger.warning(f"CSRF violation on delete_category from {request.remote_addr}")
        return jsonify({"status": "error", "message": "CSRF validation failed"}), 403
    db_manager.delete_category(cat_id)
    return redirect(url_for('categories'))

@app.route('/edit_category/<int:cat_id>', methods=['POST'])
@login_required
@csrf_required
def edit_category(cat_id):
    name = request.form.get('name')
    keywords = request.form.get('keywords')
    min_discount = request.form.get('min_discount')
    priority = request.form.get('priority', 'MEDIUM')
    post_format = request.form.get('post_format', 'default')
    if name and keywords and min_discount:
        db_manager.update_category(cat_id, name, keywords, int(min_discount), priority, post_format)
    return redirect(url_for('categories'))

# ==========================================
# ⚡ 5. FLASH LOOT SNIPER MANAGEMENT
# ==========================================
@app.route('/flash_deals')
@login_required
def flash_deals():
    all_flash_keywords = db_manager.get_all_flash_keywords()
    return render_template('flash_deals.html', flash_keywords=all_flash_keywords)

@app.route('/add_flash', methods=['POST'])
@login_required
@csrf_required
def add_flash():
    keyword = request.form.get('keyword')
    min_discount = request.form.get('min_discount')
    
    if keyword and min_discount:
        db_manager.add_flash_keyword(keyword.strip().lower(), int(min_discount))
    return redirect(url_for('flash_deals'))

@app.route('/delete_flash/<int:keyword_id>', methods=['GET', 'POST'])
@login_required
def delete_flash(keyword_id):
    # 🛡️ SECURITY: CSRF check for GET-based delete
    if request.method == 'POST':
        token = request.form.get('csrf_token')
    else:
        token = request.args.get('csrf_token')
    stored = session.get('csrf_token')
    if not stored or not token or not secrets.compare_digest(stored, token):
        auth_logger.warning(f"CSRF violation on delete_flash from {request.remote_addr}")
        return jsonify({"status": "error", "message": "CSRF validation failed"}), 403
    db_manager.delete_flash_keyword(keyword_id)
    return redirect(url_for('flash_deals'))

@app.route('/edit_flash/<int:keyword_id>', methods=['POST'])
@login_required
@csrf_required
def edit_flash(keyword_id):
    keyword = request.form.get('keyword')
    min_discount = request.form.get('min_discount')
    
    if keyword and min_discount:
        db_manager.update_flash_keyword(keyword_id, keyword.strip().lower(), int(min_discount))
    return redirect(url_for('flash_deals'))

# ==========================================
# 🚀 6. INSTANT POST (Link Paste → Turant Post)
# ==========================================
@app.route('/instant_post')
@login_required
def instant_post():
    return render_template('instant_post.html')

@app.route('/instant_post_send', methods=['POST'])
@login_required
@csrf_required
def instant_post_send():
    """
    Background thread mein product scrape + affiliate generate + Telegram post karega.
    Bot loop bilkul nahi rukega.
    """
    product_url = request.form.get('product_url', '').strip()
    post_format = request.form.get('post_format', 'default')
    
    if not product_url:
        return jsonify({"status": "error", "message": "❌ Link khali hai! Flipkart ka link paste karo."})
    
    if 'flipkart.com' not in product_url and 'fkrt.it' not in product_url:
        return jsonify({"status": "error", "message": "❌ Yeh Flipkart ka link nahi hai! Sirf Flipkart links paste karo."})
    
    def process_instant_post(url, chosen_format):
        try:
            from scraper.flipkart import scrape_single_product
            from telegram.post_format import build_deal_message, resolve_post_format
            from telegram.bot import send_telegram_deal_post
            from telegram.deal_media import post_deal_message
            
            print(f"\n🚀 [INSTANT POST] Processing: {url[:60]}...")
            
            # 1. Product page scrape karo
            deal = scrape_single_product(url)
            
            if not deal:
                print("❌ [INSTANT POST] Product scrape fail hua. Link check karo.")
                return
            
            # 2. Affiliate link generate karo (main.py ka proven logic copy)
            print("🕵️‍♂️ [INSTANT POST] Affiliate link generate kar rahe hain...")
            affiliate_link = url  # Default: original link
            
            # Method 1: ExtraPe Bot se try karo
            try:
                from userbot.extrape_agent import get_sync_link
                agent_link = get_sync_link(url)
                if agent_link and agent_link != url:
                    print(f"✅ [INSTANT POST] Agent ne link convert kar diya: {agent_link[:50]}...")
                    affiliate_link = agent_link
                else:
                    print("⚠️ [INSTANT POST] Agent ne same link return kiya. Backup try karunga...")
                    raise Exception("Agent returned same link")
            except Exception as e:
                print(f"⚠️ [INSTANT POST] Agent error: {e}")
                # Method 2: TinyURL Backup
                try:
                    from config import EXTRAPE_AFFID, EXTRAPE_PARAM1
                    import requests as req
                    affiliate_params = f"&&affid={EXTRAPE_AFFID}&affExtParam1={EXTRAPE_PARAM1}"
                    final_long_url = f"{url}{affiliate_params}"
                    api_url = f"http://tinyurl.com/api-create.php?url={final_long_url}"
                    resp = req.get(api_url, timeout=8)
                    if resp.status_code == 200:
                        affiliate_link = resp.text
                        print(f"✅ [INSTANT POST] Backup TinyURL se link ban gaya!")
                    else:
                        affiliate_link = final_long_url
                        print(f"⚠️ [INSTANT POST] TinyURL fail, long affiliate link use karunga")
                except Exception as e2:
                    print(f"❌ [INSTANT POST] Backup bhi fail: {e2}. Original link use karunga.")
                    affiliate_link = url
            
            fmt = resolve_post_format(
                is_flash=False,
                category_format=chosen_format,
                default_format=db_manager.get_setting('DEFAULT_POST_FORMAT', 'hot_deal'),
                flash_format=db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot'),
            )
            message = build_deal_message(deal, affiliate_link, fmt)
            
            # 4. Saare channels par post karo
            try:
                channels = db_manager.get_all_channels()
            except:
                channels = []
                
            if not channels:
                print("⚠️ [INSTANT POST] Koi channel add nahi hai!")
                return
            
            for channel in channels:
                try:
                    post_deal_message(send_telegram_deal_post, channel[0], message, deal)
                except Exception as e:
                    print(f"❌ [INSTANT POST] Channel {channel[0]} par send fail: {e}")
            
            # 5. DB mein save karo
            try:
                db_manager.save_deal(
                    title=deal['title'],
                    original_link=url,
                    affiliate_link=affiliate_link,
                    category="INSTANT POST",
                    product_image=deal.get('image', ''),
                    post_type="instant"
                )
            except:
                pass
                
            print(f"✅ [INSTANT POST] Deal posted successfully: {deal['title'][:40]}...")
            
        except Exception as e:
            print(f"❌ [INSTANT POST] Error: {e}")
    
    # Background thread mein chalao taaki bot loop na ruke
    thread = threading.Thread(target=process_instant_post, args=(product_url, post_format), daemon=True)
    thread.start()
    
    return jsonify({"status": "success", "message": "🚀 Processing shuru ho gaya! 10-15 sec mein Telegram par post ho jayega."})

# ==========================================
# 📋 POST HISTORY TAB
# ==========================================
@app.route('/post_history')
@login_required
def post_history():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    if page < 1: page = 1
    if per_page < 10: per_page = 10
    if per_page > 200: per_page = 200
    deals, total, total_pages, current_page = db_manager.get_all_deals_history(page, per_page)
    return render_template('post_history.html',
                           deals=deals,
                           total=total,
                           total_pages=total_pages,
                           current_page=current_page,
                           per_page=per_page)

# ==========================================
# 📺 LIVE TERMINAL CONSOLE
# ==========================================
@app.route('/live_console')
@login_required
def live_console():
    return render_template('console.html')

@app.route('/get_logs')
@login_required
def get_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    
    if not os.path.exists(log_file_path):
        return "⏳ Bot start ho raha hai... Logs abhi aana baaki hain."
    
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
    return "Log file abhi tak bani nahi hai.", 404

@app.route('/restart_bot', methods=['POST'])
@login_required
@csrf_required
def restart_bot():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write("\n[SYSTEM] 🔄 Restart Command Received! (AWS server par yeh bot ko asaliyat mein restart karega)\n")
    return jsonify({"status": "success"})

@app.route('/clear_logs', methods=['POST'])
@login_required
@csrf_required
def clear_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    open(log_file_path, 'w').close()
    return jsonify({"status": "success"})

@app.route('/toggle_bot', methods=['POST'])
@login_required
@csrf_required
def toggle_bot():
    current = db_manager.get_setting('bot_status', 'ON')
    new_status = 'OFF' if current == 'ON' else 'ON'
    db_manager.update_setting('bot_status', new_status)
    print(f"🔴 BOT STATUS CHANGED TO: {new_status}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    db_manager.init_db()
    app.run(debug=True, port=5000)