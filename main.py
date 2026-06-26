import os
import sys
import time
import requests
import random
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Isse bot ko pata chalega ki database aur analyzer folders kahan hain
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# ==========================================
# 📝 MAGIC LOGGER (Terminal ka text Web par bhejega)
# ==========================================
log_file_path = os.path.join(BASE_DIR, 'bot.log')

class Logger(object):
    _lock = threading.Lock()  # 🛡️ Thread-safe writes

    def __init__(self):
        self.terminal = sys.__stdout__  # 🛡️ HOSTING FIX: Original stdout save karo
        try:
            self.log = open(log_file_path, "a", encoding="utf-8")
        except Exception:
            self.log = None

    def write(self, message):
        with self._lock:
            try:
                sys.__stdout__.write(message)
            except Exception:
                pass
            if self.log:
                try:
                    self.log.write(message)
                    self.log.flush() 
                except Exception:
                    pass

    def flush(self):
        try:
            sys.__stdout__.flush()
        except Exception:
            pass

sys.stdout = Logger()
sys.stderr = Logger()

from analyzer.trends import get_current_trend, build_flipkart_url
from scraper.flipkart import get_flipkart_deals, scrape_keyword_full
from telegram.bot import send_telegram_message, send_telegram_deal_post
from config import EXTRAPE_AFFID, EXTRAPE_PARAM1
from database import db_manager
from userbot.extrape_agent import get_sync_link
# pick_best_deal is dead code — scoring happens inside scrape_keyword_full via score_deal
from telegram.post_format import build_deal_message, resolve_post_format
from telegram.deal_media import post_deal_message

# 🛡️ Thread-safe DB write lock
_db_lock = threading.Lock()

def is_link_already_sent(link):
    try:
        with _db_lock:
            return db_manager.is_link_already_sent(link)
    except Exception as e:
        print(f"⚠️ DB Link Check Error: {e}")
        return False

def clear_old_links():
    try:
        with _db_lock:
            total_deals = db_manager.get_total_deals_count()
            if total_deals >= 192:
                # 🛡️ SECURITY: Delete oldest 50 deals gradually instead of all-at-once
                db_manager.delete_oldest_deals(50)
                print(f"🧹 Cleanup: {total_deals} deals total. Oldest 50 deleted. Keeping recent history.")
    except Exception as e:
        print(f"⚠️ DB Count Error: {e}")


def get_affiliate_link(original_url):
    print(f"🕵️‍♂️ Secret Agent ko link bhej rahe hain...")
    try:
        # 🛡️ SECURITY: Timeout after 15s so consumer thread never blocks
        agent_link = get_sync_link(original_url)
        if agent_link and agent_link != original_url:
            print("✅ Agent ne link successfully convert kar diya!")
            return agent_link
        else:
            print("⚠️ Agent slow hai ya fail hua. Backup (Plan B) chalu kar rahe hain...")
    except Exception as e:
        print(f"❌ Agent error: {e}. Backup (Plan B) chalu kar rahe hain...")

    try:
        affiliate_params = f"&&affid={EXTRAPE_AFFID}&affExtParam1={EXTRAPE_PARAM1}"
        final_long_url = f"{original_url}{affiliate_params}"
        
        api_url = f"http://tinyurl.com/api-create.php?url={final_long_url}"
        response = requests.get(api_url, timeout=8)
        
        if response.status_code == 200:
            print("✅ Backup (TinyURL) se affiliate link ban gaya!")
            return response.text 
        
        return final_long_url
        
    except Exception as e:
        print(f"❌ Affiliate Backup Error: {e}")
        return original_url


# ==========================================
# 📬 V2: CONSUMER THREAD — Queue se deals pop karke Telegram par bhejta hai
# ==========================================
def consumer_thread(deal_queue, stop_event):
    """
    Background thread — Queue se highest priority deal pop karta hai
    aur Telegram par bhejta hai with DELAY_POST gap.
    """
    print("📬 [Consumer] Telegram Poster Thread shuru ho gaya!")
    
    while not stop_event.is_set():
        try:
            # Queue se deal uthao (5 second timeout — taaki stop_event check hota rahe)
            try:
                priority, timestamp, item = deal_queue.get(timeout=5)
            except queue.Empty:
                continue
            
            deal = item['deal']
            score = item['score']
            keyword = item['keyword']
            category = item['category']
            post_fmt = item['post_format']
            
            title_short = deal.get('title', '')[:40]
            print(f"\n📬 [Consumer] Processing: {title_short}... (Priority={priority}, Score={score['total']})")
            
            # ---- DUPLICATE CHECK (Late validation) ----
            link = deal.get('link', '')
            if is_link_already_sent(link):
                print(f"  🔁 [Consumer] Already sent, skip: {title_short}")
                deal_queue.task_done()
                continue
            
            # ---- AFFILIATE LINK GENERATE ----
            try:
                final_affiliate_link = get_affiliate_link(link)
            except Exception as e:
                print(f"  ❌ [Consumer] Affiliate link error: {e}")
                final_affiliate_link = link
            
            # ---- FORMAT MESSAGE ----
            try:
                resolved_fmt = resolve_post_format(
                    is_flash=(priority <= 1),
                    category_format=post_fmt,
                    default_format=db_manager.get_setting('DEFAULT_POST_FORMAT', 'hot_deal'),
                    flash_format=db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot'),
                )
                message = build_deal_message(deal, final_affiliate_link, resolved_fmt)
            except Exception as e:
                print(f"  ❌ [Consumer] Message format error: {e}")
                deal_queue.task_done()
                continue
            
            # ---- SEND TO ALL CHANNELS ----
            try:
                with _db_lock:
                    channels = db_manager.get_all_channels()
            except Exception as e:
                print(f"  ❌ [Consumer] Channel DB error: {e}")
                channels = []
            
            if channels:
                for channel in channels:
                    try:
                        post_deal_message(
                            send_telegram_deal_post, channel[0], message, deal
                        )
                        print(f"  ✅ [Consumer] Sent to {channel[0]}: {title_short}")
                    except Exception as e:
                        print(f"  ❌ [Consumer] Telegram error ({channel[0]}): {e}")
            else:
                print("  ⚠️ [Consumer] Koi channel nahi hai!")
            
            # ---- SAVE TO DATABASE ----
            try:
                with _db_lock:
                    post_type = "flash" if priority <= 1 else "normal"
                    db_manager.save_deal(
                        title=deal.get('title', ''),
                        original_link=link,
                        affiliate_link=final_affiliate_link,
                        category=category,
                        product_image=deal.get('image', ''),
                        post_type=post_type
                    )
            except Exception as e:
                print(f"  ⚠️ [Consumer] Deal save error: {e}")
            
            deal_queue.task_done()
            
            # ---- DELAY BEFORE NEXT POST (Dashboard controlled, min 60s enforced) ----
            try:
                delay = int(db_manager.get_setting('QUEUE_DELAY_POST', 15))
            except Exception:
                delay = 15
            # 🛡️ Enforce minimum 60s gap to prevent spammy posting
            if delay < 60:
                print(f"  ⚠️ [Consumer] QUEUE_DELAY_POST={delay}s is too low. Enforcing minimum 60s.")
                delay = 60
                try:
                    db_manager.update_setting('QUEUE_DELAY_POST', '60')
                except Exception:
                    pass
            
            print(f"  ⏳ [Consumer] {delay}s wait before next post...")
            
            # Sleep in small chunks taaki stop_event check hota rahe
            for _ in range(delay):
                if stop_event.is_set():
                    break
                time.sleep(1)
        
        except Exception as e:
            print(f"  ❌ [Consumer] Error: {e}")
            time.sleep(5)
    
    print("📬 [Consumer] Thread stopped.")


# ==========================================
# ⚡ FLASH SALE TRACKER (V2 — Parallel + Queue Push)
# ==========================================
flash_cooldowns = {}
_flash_lock = threading.Lock()  # 🛡️ Thread-safe access to flash_cooldowns

def check_flash_sales(deal_queue):
    """Flash deals ko parallel scrape karo aur queue mein daalo (Priority 0 — sabse pehle post)."""
    try:
        print("\n⚡ [FLASH] Saare targets ek saath check ho rahe hain...")
        
        try:
            flash_data = db_manager.get_all_flash_keywords()
        except Exception as e:
            print(f"❌ [FLASH] Flash Keywords DB Error: {e}")
            return
        
        if not flash_data:
            print("⚠️ [FLASH] Dashboard mein koi target set nahi hai.")
            return
        
        current_time = time.time()
        available = []
        with _flash_lock:
            for target in flash_data:
                try:
                    keyword = target[1]
                    last_used = flash_cooldowns.get(keyword, 0)
                    if (current_time - last_used) > 86400:  # 24hr lock
                        available.append(target)
                except (IndexError, TypeError):
                    continue
        
        if not available:
            print("⏳ [FLASH] Saare targets 24hr locked hain.")
            return
        
        print(f"🎯 [FLASH] {len(available)} active targets. Parallel scrape shuru...")
        
        try:
            min_buyers = int(db_manager.get_setting('MIN_BUYERS_COUNT', 1000))
            allow_missing = db_manager.get_setting('ALLOW_MISSING_BUYERS', 'OFF') == 'ON'
        except Exception:
            min_buyers = 1000
            allow_missing = False
        
        max_flash_workers = min(len(available), 3)  # Max 3 parallel flash scrapers
        
        with ThreadPoolExecutor(max_workers=max_flash_workers) as flash_executor:
            futures = {}
            for target in available:
                try:
                    flash_keyword = target[1]
                    target_discount = int(target[2]) if target[2] else 50
                except (IndexError, ValueError, TypeError):
                    continue
                
                flash_settings = {
                    'min_discount': target_discount,
                    'min_buyers_count': min_buyers,
                    'max_pages': 1,  # Flash deals = sirf Page 1 (speed ke liye)
                    'category_name': 'FLASH LOOT',
                    'priority_weight': 4,  # HIGH priority
                    'post_format': db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot'),
                    'allow_missing_buyers': allow_missing,
                }
                
                # Staggered start — 2 sec gap between flash scrapers
                time.sleep(random.uniform(1, 3))
                
                future = flash_executor.submit(
                    scrape_keyword_full,
                    flash_keyword,
                    flash_settings,
                    deal_queue,
                    is_link_already_sent,
                )
                futures[future] = flash_keyword
            
            for future in as_completed(futures):
                keyword = futures[future]
                try:
                    future.result()
                    with _flash_lock:
                        flash_cooldowns[keyword] = current_time  # 24hr lock
                    print(f"🔒 [FLASH] '{keyword}' locked for 24 hours.")
                except Exception as e:
                    print(f"❌ [FLASH] '{keyword}' error: {e}")
    
    except Exception as e:
        print(f"❌ [FLASH] CRITICAL ERROR: {e}")
        print("🔄 Bot continue karega...")


# ==========================================
# 🤖 V2: MAIN BOT LOGIC (ThreadPool + PriorityQueue)
# ==========================================
def run_bot():
    print("🤖 Deal Hunter Bot V2 (Priority Queue Architecture) Start!")
    
    try:
        ss = db_manager.normalize_price_screenshot_setting(
            db_manager.get_setting("PRICE_SCREENSHOT", "OFF")
        )
        print(f"📷 Price screenshot: {ss}")
    except Exception as e:
        print(f"⚠️ Could not read PRICE_SCREENSHOT setting: {e}")
    
    # ---- SHARED PRIORITY QUEUE ----
    deal_queue = queue.PriorityQueue()
    
    # ---- START CONSUMER THREAD ----
    stop_event = threading.Event()
    poster = threading.Thread(
        target=consumer_thread,
        args=(deal_queue, stop_event),
        daemon=True,
        name="TelegramPoster"
    )
    poster.start()
    
    # ---- MAIN LOOP VARIABLES ----
    round_in_hour = 0
    is_live_trend_round = True
    
    saved_memory = db_manager.get_setting('used_keywords', '')
    used_keywords = set(saved_memory.split(',')) if saved_memory else set()
    print(f"🧠 Memory Loaded: {len(used_keywords)} keywords remembered.")
    
    while True:
        try:
            # 🛡️ EMERGENCY KILL SWITCH CHECK
            try:
                bot_status = db_manager.get_setting('bot_status', 'ON')
            except Exception:
                bot_status = 'ON'
            
            if bot_status == 'OFF':
                print("💤 Bot is PAUSED from Dashboard. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            # ---- READ CATEGORIES FROM DATABASE ----
            try:
                db_categories = db_manager.get_all_categories()
            except Exception as e:
                print(f"❌ Categories DB Error: {e}. 2 min wait...")
                time.sleep(120)
                continue
            
            if not db_categories:
                print("⚠️ Dashboard mein koi category/keyword nahi mila. 2 min wait...")
                time.sleep(120)
                continue
            
            db_categories = db_manager.order_categories_by_priority(db_categories)
            keyword_weights = db_manager.build_keyword_weights(db_categories)
            
            priority_summary = ', '.join(
                f"{cat[1]}={db_manager.normalize_priority(cat[4] if len(cat) > 4 else 'MEDIUM')}"
                for cat in db_categories
            )
            print(f"📌 Category priorities: {priority_summary}")
            
            # Build category lookup maps
            MARKET_DATA = {}
            ALL_KEYWORDS_SET = set()
            category_priority_map = {}
            category_format_map = {}
            
            for cat in db_categories:
                try:
                    cat_name = cat[1]
                    cat_keywords = [k.strip().lower() for k in cat[2].split(',')]
                    min_disc = int(cat[3])
                    priority = cat[4] if len(cat) > 4 else 'MEDIUM'
                    post_fmt = cat[5] if len(cat) > 5 else 'default'
                    
                    MARKET_DATA[cat_name] = {
                        "keywords": cat_keywords,
                        "min_discount": min_disc
                    }
                    ALL_KEYWORDS_SET.update(cat_keywords)
                    category_priority_map[cat_name] = db_manager.get_priority_weight(priority)
                    category_format_map[cat_name] = post_fmt
                except (IndexError, TypeError, ValueError) as e:
                    print(f"⚠️ Category data corrupt, skip: {e}")
                    continue
            
            if not ALL_KEYWORDS_SET:
                print("⚠️ Koi valid keyword nahi mila. 2 min wait...")
                time.sleep(120)
                continue
            
            used_keywords = used_keywords.intersection(ALL_KEYWORDS_SET)
            clear_old_links()
            
            # ---- READ DYNAMIC SETTINGS FROM DATABASE ----
            try:
                keywords_per_round = max(1, min(10, int(db_manager.get_setting('KEYWORDS_PER_ROUND', 4))))
                max_workers = max(1, min(6, int(db_manager.get_setting('MAX_WORKERS', 2))))
                min_buyers = int(db_manager.get_setting('MIN_BUYERS_COUNT', 1000))
                max_pages = max(1, min(5, int(db_manager.get_setting('MAX_SCRAPE_PAGES', 3))))
                allow_missing = db_manager.get_setting('ALLOW_MISSING_BUYERS', 'OFF') == 'ON'
            except Exception:
                keywords_per_round, max_workers, min_buyers, max_pages = 4, 2, 1000, 3
                allow_missing = False
            
            if is_live_trend_round:
                round_label = "LIVE MARKET TREND"
            else:
                round_label = "DATABASE ROTATION"
            
            print(f"\n{'='*55}")
            print(f"🚀 [ROUND {round_in_hour+1}/4] : {round_label}")
            print(f"   Workers={max_workers} | MinBuyers={min_buyers} | MaxPages={max_pages}")
            print(f"{'='*55}")
            
            # ---- SELECT KEYWORDS FOR THIS ROUND ----
            keywords_to_scrape = []
            
            # Live trend (har doosre round mein)
            if is_live_trend_round:
                try:
                    trend = get_current_trend(list(ALL_KEYWORDS_SET))
                    print(f"🔥 Trending Keyword: {trend}")
                    if trend not in used_keywords:
                        keywords_to_scrape.append(trend)
                    else:
                        print(f"⚠️ '{trend}' pehle use ho chuka. DB backup se lenge.")
                except Exception as e:
                    print(f"⚠️ Google Trends error: {e}. DB backup use karunga.")
            
            # Baaki keywords DB se (weighted random)
            remaining_pool = list(ALL_KEYWORDS_SET - used_keywords - set(keywords_to_scrape))
            if not remaining_pool:
                used_keywords.clear()
                remaining_pool = list(ALL_KEYWORDS_SET - set(keywords_to_scrape))
            
            while len(keywords_to_scrape) < keywords_per_round and remaining_pool:
                picked = db_manager.pick_weighted_keyword(remaining_pool, keyword_weights)
                keywords_to_scrape.append(picked)
                remaining_pool.remove(picked)
            
            print(f"📋 Is round mein scrape honge: {keywords_to_scrape}")
            
            # ---- PARALLEL SCRAPING (THE PRODUCERS) ----
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                
                for idx, kw in enumerate(keywords_to_scrape):
                    # Find matching category for this keyword
                    matched_cat = None
                    matched_discount = 60
                    for cat_name, data in MARKET_DATA.items():
                        if kw in data['keywords']:
                            matched_cat = cat_name
                            matched_discount = data['min_discount']
                            break
                    
                    # Partial match fallback
                    if matched_cat is None:
                        for cat_name, data in MARKET_DATA.items():
                            if any(keyword in kw for keyword in data['keywords']):
                                matched_cat = cat_name
                                matched_discount = data['min_discount']
                                break
                    
                    if matched_cat is None:
                        matched_discount = 60
                    
                    kw_settings = {
                        'min_discount': matched_discount,
                        'min_buyers_count': min_buyers,
                        'max_pages': max_pages,
                        'category_name': matched_cat or 'GENERAL',
                        'priority_weight': category_priority_map.get(matched_cat, 2),
                        'post_format': category_format_map.get(matched_cat, 'hot_deal'),
                        'allow_missing_buyers': allow_missing,
                    }
                    
                    # Staggered start — 2-4 sec gap between scrapers (anti-ban)
                    if idx > 0:
                        stagger = random.uniform(2, 4)
                        print(f"  ⏳ Staggered start: {stagger:.1f}s wait before '{kw}'...")
                        time.sleep(stagger)
                    
                    print(f"\n🔍 [{idx+1}/{len(keywords_to_scrape)}] Submitting: '{kw}' (Cat={matched_cat or 'GENERAL'}, Min={matched_discount}%)")
                    
                    future = executor.submit(
                        scrape_keyword_full,
                        kw,
                        kw_settings,
                        deal_queue,
                        is_link_already_sent,
                    )
                    futures[future] = kw
                
                # Wait for all scrapers to finish
                for future in as_completed(futures):
                    kw = futures[future]
                    try:
                        future.result()
                        used_keywords.add(kw)
                        print(f"✅ Scraper done: '{kw}'")
                    except Exception as e:
                        print(f"❌ Scraper error ({kw}): {e}")
                        used_keywords.add(kw)  # Mark as used even on error
            
            # Save used keywords to DB
            with _db_lock:
                db_manager.update_setting('used_keywords', ','.join(used_keywords))
            
            is_live_trend_round = not is_live_trend_round
            round_in_hour += 1
            
            print(f"\n📊 Queue size after round: {deal_queue.qsize()} deals pending")
            
        except Exception as e:
            print(f"❌ Main loop error: {e}")
        
        # ==========================================
        # ⏰ WAIT PERIOD (with Flash Sale checks)
        # ==========================================
        try:
            round_wait = int(db_manager.get_setting('ROUND_WAIT', 15))
        except Exception:
            round_wait = 15
        try:
            long_sleep = int(db_manager.get_setting('LONG_SLEEP', 60))
        except Exception:
            long_sleep = 60
        try:
            flash_interval = max(1, int(db_manager.get_setting('FLASH_INTERVAL', 3)))
        except Exception:
            flash_interval = 3
        
        if round_in_hour < 4:
            wait_minutes = max(1, round_wait)
            print(f"\n⏳ Round {round_in_hour}/4 complete. {wait_minutes} min wait. Flash check har {flash_interval} min...")
        else:
            wait_minutes = max(1, long_sleep)
            round_in_hour = 0
            print(f"\n😴 4 Round quota poora! {wait_minutes} min wait. Flash check har {flash_interval} min...")
        
        # 🟢 THE FLASH SALE LOOP WITH INSTANT STOP
        cycles = (wait_minutes * 60) // 10  # 10 second ke chote gaps
        
        for i in range(cycles):
            try:
                if db_manager.get_setting('bot_status', 'ON') == 'OFF':
                    break
            except Exception:
                pass
            
            time.sleep(10)
            
            # Har X minute par flash sales check karo
            try:
                if (i * 10) % (flash_interval * 60) == 0 and i != 0:
                    check_flash_sales(deal_queue)
            except Exception as e:
                print(f"⚠️ Flash sale check error: {e}")


if __name__ == "__main__":
    try:
        db_manager.init_db()
    except Exception as e:
        print(f"❌ CRITICAL: Database init fail: {e}")
        print("💡 Check file permissions on the server.")
    
    # 🚨 KOYEB FIX: Dashboard aur Bot ko sath chalane ke liye
    from dashboard.app import app
    
    print("🌐 Starting Dashboard on Port 8000...")
    
    def start_dashboard():
        try:
            # 🛡️ SECURITY: Bind to localhost only — prevents external network access to admin panel
            #    Use nginx reverse proxy + Cloudflare Tunnel if remote access is needed
            app.run(host='127.0.0.1', port=8000)
        except Exception as e:
            print(f"❌ Dashboard error: {e}")
            print("⚠️ Dashboard band hai lekin Bot chalta rahega!")
            
    threading.Thread(target=start_dashboard, daemon=True).start()
    
    time.sleep(5)
    
    # 🛡️ MASTER SAFETY: Bot kabhi band nahi hoga
    while True:
        try:
            run_bot()
        except KeyboardInterrupt:
            print("\n⛔ Bot manually band kiya gaya (Ctrl+C). Bye!")
            break
        except Exception as e:
            print(f"❌❌ BOT CRASH DETECTED: {e}")
            print("🔄 AUTO-RESTART: Bot 30 sec mein wapas shuru hoga...")
            time.sleep(30)