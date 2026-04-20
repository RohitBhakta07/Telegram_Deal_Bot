from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
import sys
import os
import psutil

# Database file path setup
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from database import db_manager

app = Flask(__name__)

@app.route('/')
def index():
    status = db_manager.get_setting('bot_status', 'ON')
    return render_template('index.html', bot_status=status)

# 2. Settings Page
@app.route('/settings')
def settings():
    api_id = db_manager.get_setting('API_ID', '')
    api_hash = db_manager.get_setting('API_HASH', '')
    bot_token = db_manager.get_setting('BOT_TOKEN', '')
    extrape_affid = db_manager.get_setting('EXTRAPE_AFFID', '')
    extrape_param1 = db_manager.get_setting('EXTRAPE_PARAM1', '')
    # ⚡ Bot Speed & Timing Settings (Defaults ke sath)
    delay_post = db_manager.get_setting('DELAY_POST', '5')
    delay_retry = db_manager.get_setting('DELAY_RETRY', '9')
    flash_interval = db_manager.get_setting('FLASH_INTERVAL', '3')
    round_wait = db_manager.get_setting('ROUND_WAIT', '15')
    long_sleep = db_manager.get_setting('LONG_SLEEP', '60')

    return render_template('settings.html', 
                           api_id=api_id, api_hash=api_hash, bot_token=bot_token,
                           extrape_affid=extrape_affid, extrape_param1=extrape_param1,
                           delay_post=delay_post, delay_retry=delay_retry, 
                           flash_interval=flash_interval, round_wait=round_wait, long_sleep=long_sleep)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    if request.method == 'POST':
        db_manager.update_setting('API_ID', request.form.get('api_id'))
        db_manager.update_setting('API_HASH', request.form.get('api_hash'))
        db_manager.update_setting('BOT_TOKEN', request.form.get('bot_token'))
        db_manager.update_setting('EXTRAPE_AFFID', request.form.get('extrape_affid'))
        db_manager.update_setting('EXTRAPE_PARAM1', request.form.get('extrape_param1'))
        # Save Speed Settings
        db_manager.update_setting('DELAY_POST', request.form.get('delay_post'))
        db_manager.update_setting('DELAY_RETRY', request.form.get('delay_retry'))
        db_manager.update_setting('FLASH_INTERVAL', request.form.get('flash_interval'))
        db_manager.update_setting('ROUND_WAIT', request.form.get('round_wait'))
        db_manager.update_setting('LONG_SLEEP', request.form.get('long_sleep'))

        return redirect(url_for('settings'))

# 3. Channels Page 
@app.route('/channels')
def channels():
    all_channels = db_manager.get_all_channels()
    return render_template('channels.html', channels=all_channels)

@app.route('/add_channel', methods=['POST'])
def add_channel():
    channel_id = request.form.get('channel_id')
    channel_name = request.form.get('channel_name')
    if channel_id and channel_name:
        db_manager.add_channel(channel_id, channel_name)
    return redirect(url_for('channels'))

@app.route('/delete_channel/<channel_id>')
def delete_channel(channel_id):
    db_manager.delete_channel(channel_id)
    return redirect(url_for('channels'))

# ==========================================
# 4. CATEGORIES MANAGEMENT 
# ==========================================
@app.route('/categories')
def categories():
    all_categories = db_manager.get_all_categories()
    return render_template('categories.html', categories=all_categories)

@app.route('/add_category', methods=['POST'])
def add_category():
    name = request.form.get('name')
    keywords = request.form.get('keywords') 
    min_discount = request.form.get('min_discount')
    
    if name and keywords and min_discount:
        db_manager.add_category(name, keywords, int(min_discount))
    return redirect(url_for('categories'))

@app.route('/delete_category/<cat_id>')
def delete_category(cat_id):
    db_manager.delete_category(cat_id)
    return redirect(url_for('categories'))

@app.route('/edit_category/<int:cat_id>', methods=['POST'])
def edit_category(cat_id):
    name = request.form.get('name')
    keywords = request.form.get('keywords')
    min_discount = request.form.get('min_discount')
    
    if name and keywords and min_discount:
        db_manager.update_category(cat_id, name, keywords, int(min_discount))
    return redirect(url_for('categories'))

# ==========================================
# ⚡ 5. FLASH LOOT SNIPER MANAGEMENT
# ==========================================
@app.route('/flash_deals')
def flash_deals():
    all_flash_keywords = db_manager.get_all_flash_keywords()
    return render_template('flash_deals.html', flash_keywords=all_flash_keywords)

@app.route('/add_flash', methods=['POST'])
def add_flash():
    keyword = request.form.get('keyword')
    min_discount = request.form.get('min_discount')
    
    if keyword and min_discount:
        db_manager.add_flash_keyword(keyword.strip().lower(), int(min_discount))
    return redirect(url_for('flash_deals'))

@app.route('/delete_flash/<int:keyword_id>')
def delete_flash(keyword_id):
    db_manager.delete_flash_keyword(keyword_id)
    return redirect(url_for('flash_deals'))

@app.route('/edit_flash/<int:keyword_id>', methods=['POST'])
def edit_flash(keyword_id):
    keyword = request.form.get('keyword')
    min_discount = request.form.get('min_discount')
    
    if keyword and min_discount:
        db_manager.update_flash_keyword(keyword_id, keyword.strip().lower(), int(min_discount))
    return redirect(url_for('flash_deals'))

# ==========================================
# 📺 LIVE TERMINAL CONSOLE
# ==========================================
@app.route('/live_console')
def live_console():
    return render_template('console.html')

@app.route('/get_logs')
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
def system_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    mem_used_mb = int(mem.used / (1024 * 1024))
    return jsonify({'cpu': cpu, 'mem': mem_used_mb})

@app.route('/export_logs')
def export_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    if os.path.exists(log_file_path):
        return send_file(log_file_path, as_attachment=True, download_name='Deal_Hunter_Logs.txt')
    return "Log file abhi tak bani nahi hai.", 404

@app.route('/restart_bot', methods=['POST'])
def restart_bot():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write("\n[SYSTEM] 🔄 Restart Command Received! (AWS server par yeh bot ko asaliyat mein restart karega)\n")
    return jsonify({"status": "success"})

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    log_file_path = os.path.join(parent_dir, 'bot.log')
    open(log_file_path, 'w').close()
    return jsonify({"status": "success"})

@app.route('/toggle_bot', methods=['POST'])
def toggle_bot():
    current = db_manager.get_setting('bot_status', 'ON')
    new_status = 'OFF' if current == 'ON' else 'ON'
    db_manager.update_setting('bot_status', new_status)
    print(f"🔴 BOT STATUS CHANGED TO: {new_status}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    db_manager.init_db()
    app.run(debug=True, port=5000)