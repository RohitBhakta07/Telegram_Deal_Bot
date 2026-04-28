import os
import sys
import time
import requests
import random

# Isse bot ko pata chalega ki database aur analyzer folders kahan hain
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# ==========================================
# 📝 MAGIC LOGGER (Terminal ka text Web par bhejega)
# ==========================================
log_file_path = os.path.join(BASE_DIR, 'bot.log')

class Logger(object):
    def __init__(self):
        self.terminal = sys.__stdout__  # 🛡️ HOSTING FIX: Original stdout save karo, Logger-in-Logger se bachne ke liye
        try:
            self.log = open(log_file_path, "a", encoding="utf-8")
        except Exception:
            self.log = None  # 🛡️ Agar log file nahi khul paaye (permission error on server)

    def write(self, message):
        try:
            self.terminal.write(message)
        except Exception:
            pass
        if self.log:
            try:
                self.log.write(message)
                self.log.flush() 
            except Exception:
                pass  # 🛡️ Disk full ya write permission error handle

    def flush(self):
        try:
            self.terminal.flush()
        except Exception:
            pass

sys.stdout = Logger()
sys.stderr = Logger()

from analyzer.trends import get_current_trend, build_flipkart_url
from scraper.flipkart import get_flipkart_deals
from telegram.bot import send_telegram_message  
from config import EXTRAPE_AFFID, EXTRAPE_PARAM1
from database import db_manager
from userbot.extrape_agent import get_sync_link
from analyzer.fake_drop import is_genuine_deal

def is_link_already_sent(link):
    try:
        return db_manager.is_link_already_sent(link)
    except Exception as e:
        print(f"⚠️ DB Link Check Error: {e}")
        return False  # 🛡️ Agar DB down ho toh deal bhejne do, duplicate se crash better hai

def clear_old_links():
    try:
        total_deals = db_manager.get_total_deals_count()
        if total_deals >= 192 :
            db_manager.clear_all_deals()  
            print(f"🧹 Memory Reset: {total_deals} deals poori hui. Naya cycle shuru!")
    except Exception as e:
        print(f"⚠️ DB Count Error: {e}")

def get_affiliate_link(original_url):
    print(f"🕵️‍♂️ Secret Agent ko link bhej rahe hain...")
    try:
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
# ⚡ THE FLASH SALE TRACKER (ALL Blocks Checked + 24 Hr Lock)
# ==========================================
flash_cooldowns = {}

def check_flash_sales():
    try:
        print("\n⚡ [NINJA TRACKER] Saare MEGA LOOT targets check kar rahe hain...")
        
        try:
            flash_data = db_manager.get_all_flash_keywords()
        except Exception as e:
            print(f"❌ Flash Keywords DB Error: {e}")
            return
        
        if not flash_data:
            print("⚠️ Sniper Tracker: Dashboard mein koi target set nahi hai. Skip kar rahe hain.")
            return

        current_time = time.time()
        available_targets = []
        
        for target in flash_data:
            try:
                keyword = target[1]
                last_used_time = flash_cooldowns.get(keyword, 0)
                
                # Check: Kya is keyword ko use hue 24 ghante (86400 seconds) ho gaye hain?
                if (current_time - last_used_time) > 86400:
                    available_targets.append(target)
            except (IndexError, TypeError) as e:
                print(f"⚠️ Flash target data corrupt, skip: {e}")
                continue
                
        if not available_targets:
            print("⏳ Sniper Alert: Saare Flash Targets par 24-Ghante ka Lock laga hua hai. Market shant hai.")
            return

        print(f"🎯 Total {len(available_targets)} active targets mile. Ek-ek karke sabko check kar rahe hain...\n")

        for target in available_targets:
            try:
                flash_keyword = target[1] 
                target_discount = target[2] 
                
                # 🛡️ HOSTING FIX: Agar discount galat type mein aaye
                try:
                    target_discount = int(target_discount)
                except (ValueError, TypeError):
                    target_discount = 50  # Safe default
                
                print(f"🔍 Scanning Target: '{flash_keyword.upper()}' (Min {target_discount}% DROP)")
                
                target_url = build_flipkart_url(flash_keyword, min_discount=target_discount) 
                deals = get_flipkart_deals(target_url, required_discount=target_discount)
                
                if deals:
                    random.shuffle(deals)
                    for deal in deals:
                        try:
                            if not is_genuine_deal(deal['title'], deal['price'], deal['mrp'], deal['discount']):
                                continue
                            if is_link_already_sent(deal['link']):
                                print(f"🔁 Repeat skipped: {deal['title']}")
                                continue

                            final_affiliate_link = get_affiliate_link(deal['link'])
                            
                            message = f"""🚨 <b>MEGA LOOT ALERT | PRICE DROP</b> 🚨

🛍️ {deal['title']}

💰 <b>MRP : </b> <del>{deal['mrp']}</del>
💸 <b>Loot Price : </b> {deal['price']}
📉 <b>Flat {deal['discount']}</b>

👉 <b>Loot Fast (Stock ends in mins): 👇</b> 
{final_affiliate_link}

⚡ <b>Flash Deal:</b> Yeh deal kisi bhi waqt Sold Out ho sakti hai!"""
                            
                            try:
                                channels = db_manager.get_all_channels()
                            except Exception as e:
                                print(f"❌ Channel DB Error: {e}")
                                channels = []
                                
                            if channels:
                                for channel in channels:
                                    try:
                                        send_telegram_message(message, image_url=deal.get('image'), chat_id=channel[0])
                                    except Exception as e:
                                        print(f"❌ Telegram send error (channel {channel[0]}): {e}")
                            
                            try:
                                db_manager.save_deal(
                                    title=deal['title'],
                                    original_link=deal['link'],
                                    affiliate_link=final_affiliate_link,
                                    category="FLASH LOOT"
                                )
                            except Exception as e:
                                print(f"⚠️ Deal save error: {e}")
                                
                            print(f"🚨🚨 FLASH DEAL SENT: {deal['title']} 🚨🚨")
                            
                            # 🔒 THE 24-HOUR LOCK
                            flash_cooldowns[flash_keyword] = current_time
                            print(f"🔒 KEYWORD LOCKED: '{flash_keyword}' ab agle 24 ghante tak search nahi hoga!\n")
                            
                            break
                        except KeyError as e:
                            print(f"⚠️ Deal data incomplete (missing key: {e}), skip...")
                            continue
                else:
                    print(f"📉 Deal nahi mili.\n")

                # 🛑 ANTI-BAN DELAY (Admin Controlled)
                try:
                    delay_post = int(db_manager.get_setting('DELAY_POST', 5))
                except Exception:
                    delay_post = 5
                time.sleep(delay_post) 
                
            except Exception as e:
                print(f"❌ Flash target processing error: {e}")
                continue
                
    except Exception as e:
        print(f"❌ FLASH SALES CRITICAL ERROR: {e}")
        print("🔄 Bot continue karega...")

# ==========================================
# 🤖 ASALI BOT LOGIC 
# ==========================================
def run_bot():
    print("🤖 Deal Hunter Bot Start ho gaya hai...\n")
    
    round_in_hour = 0 
    used_keywords = set()  
    is_live_trend_round = True  

    while True:
        try:
            # 🛡️ EMERGENCY KILL SWITCH CHECK
            try:
                bot_status = db_manager.get_setting('bot_status', 'ON')
            except Exception as e:
                print(f"⚠️ DB status check fail: {e}. Assuming ON...")
                bot_status = 'ON'
            
            if bot_status == 'OFF':
                print("💤 Bot is PAUSED from Dashboard. Waiting 60 seconds...")
                time.sleep(60)
                continue
     
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

            MARKET_DATA = {}
            ALL_KEYWORDS_SET = set()

            for cat in db_categories:
                try:
                    cat_name = cat[1]
                    cat_keywords = [k.strip().lower() for k in cat[2].split(',')]
                    min_disc = int(cat[3])

                    MARKET_DATA[cat_name] = {
                        "keywords": cat_keywords,
                        "min_discount": min_disc
                    }
                    ALL_KEYWORDS_SET.update(cat_keywords)
                except (IndexError, TypeError, ValueError) as e:
                    print(f"⚠️ Category data corrupt, skip: {e}")
                    continue

            # 🛡️ HOSTING FIX: Agar saari categories corrupt hain toh empty set hoga
            if not ALL_KEYWORDS_SET:
                print("⚠️ Koi valid keyword nahi mila categories mein. 2 min wait...")
                time.sleep(120)
                continue

            used_keywords = used_keywords.intersection(ALL_KEYWORDS_SET)
            clear_old_links() 
            
            max_attempts = 3
            current_attempt = 1
            deals_sent_this_round = 0
            
            if is_live_trend_round:
                print("\n==================================================")
                print(f"🌍 [ROUND {round_in_hour+1}/4] : LIVE MARKET TREND")
                print("==================================================")
            else:
                print("\n==================================================")
                print(f"📦 [ROUND {round_in_hour+1}/4] : DATABASE ROTATION")
                print("==================================================")

            while deals_sent_this_round < 2 and current_attempt <= max_attempts:
                print(f"\n🔄 --- ATTEMPT {current_attempt}/{max_attempts} ---")
                
                # 🚀 NEW: Har attempt ke start mein KEYWORDS_PER_ROUND DB se padho
                # (Agar beech mein dashboard se change kiya toh agle attempt mein apply hoga)
                try:
                    keywords_per_round = int(db_manager.get_setting('KEYWORDS_PER_ROUND', 1))
                except Exception:
                    keywords_per_round = 1
                if keywords_per_round < 1:
                    keywords_per_round = 1
                if keywords_per_round > 10:
                    keywords_per_round = 10
                    
                print(f"🔢 Keywords Per Round: {keywords_per_round}")
                
                # 🚀 MULTI-KEYWORD LOOP: N keywords ek saath scrape karo
                keywords_to_scrape = []
                
                # Pehla keyword: Trend ya DB rotation (existing logic)
                if is_live_trend_round and len(keywords_to_scrape) == 0:
                    try:
                        trend = get_current_trend(list(ALL_KEYWORDS_SET))
                    except Exception as e:
                        print(f"⚠️ Google Trends error: {e}. Database se backup le rahe hain...")
                        trend = random.choice(list(ALL_KEYWORDS_SET))
                        
                    print(f"🔥 Aaj ka Trending Keyword: {trend}")
                    
                    if trend not in used_keywords:
                        keywords_to_scrape.append(trend)
                    else:
                        print(f"⚠️ SYSTEM OVERRIDE: '{trend}' pehle hi post ho chuka hai. DB Backup use karunga.")
                
                # Baaki keywords DB se unique nikalo
                remaining_pool = list(ALL_KEYWORDS_SET - used_keywords - set(keywords_to_scrape))
                if not remaining_pool:
                    used_keywords.clear()
                    remaining_pool = list(ALL_KEYWORDS_SET - set(keywords_to_scrape))
                
                random.shuffle(remaining_pool)
                while len(keywords_to_scrape) < keywords_per_round and remaining_pool:
                    keywords_to_scrape.append(remaining_pool.pop(0))
                
                print(f"📋 Is attempt mein scrape honge: {keywords_to_scrape}")
                
                # Har keyword ke liye scrape karo
                for kw_index, final_search_keyword in enumerate(keywords_to_scrape):
                    if deals_sent_this_round >= 2:
                        break  # 2 deals ho gayi, ruk jao
                    
                    print(f"\n  🔍 [{kw_index+1}/{len(keywords_to_scrape)}] Keyword: '{final_search_keyword}'")
                    
                    target_discount = None
                    matched_category = None

                    for category, data in MARKET_DATA.items():
                        if final_search_keyword in data["keywords"]:
                            target_discount = data["min_discount"]
                            matched_category = category
                            break
                    
                    # Agar exact match nahi mila toh partial match try karo
                    if target_discount is None:
                        for category, data in MARKET_DATA.items():
                            if any(keyword in final_search_keyword for keyword in data["keywords"]): 
                                target_discount = data["min_discount"]      
                                matched_category = category
                                break

                    # 🛡️ HOSTING FIX: Agar target_discount None reh gaya (koi match nahi mila)
                    if target_discount is None:
                        target_discount = 60  # Safe default

                    print(f"  📊 Match: {matched_category.upper() if matched_category else 'GENERAL'} (Min {target_discount}% Off)")

                    target_url = build_flipkart_url(final_search_keyword, min_discount=target_discount) 
                    deals = get_flipkart_deals(target_url, required_discount=target_discount)
                
                    if deals:
                        random.shuffle(deals)
                        for deal in deals:
                            try:
                                if is_link_already_sent(deal['link']):
                                    print(f"🔁 Repeat skipped: {deal['title']}")
                                    continue
                                if deals_sent_this_round >= 2:
                                    break
                                    
                                final_affiliate_link = get_affiliate_link(deal['link'])
                                
                                message = f"""🔥 <b>HOT DEAL | Verified  ✅</b>

🛍️ {deal['title']}

💰 <b>MRP : </b> <del>{deal['mrp']}</del>
💸 <b>Deal Price : </b> {deal['price']}
📉 <b>Flat {deal['discount']}</b>

👉 <b>Check price on Flipkart: 👇</b> 
{final_affiliate_link}

⭐ <b>Rating : </b> {deal['rating']}
📝 <b>Product Highlights:</b>
{deal['highlights']}
⚡ Limited time deal
⏳ Stock fast finish hota hai!"""
                                
                                try:
                                    channels = db_manager.get_all_channels()
                                except Exception as e:
                                    print(f"❌ Channel DB Error: {e}")
                                    channels = []
                                    
                                if not channels:
                                    print("⚠️ Warning: Koi channel add nahi hai!")
                                else:
                                    for channel in channels:
                                        try:
                                            send_telegram_message(message, image_url=deal.get('image'), chat_id=channel[0])
                                        except Exception as e:
                                            print(f"❌ Telegram send error (channel {channel[0]}): {e}")
                            
                                try:
                                    db_manager.save_deal(
                                        title=deal['title'],
                                        original_link=deal['link'],
                                        affiliate_link=final_affiliate_link,
                                        category=matched_category if matched_category else "GENERAL"
                                    )
                                except Exception as e:
                                    print(f"⚠️ Deal save error: {e}")

                                used_keywords.add(final_search_keyword) 
                                deals_sent_this_round += 1 
                                
                                # 🛑 ANTI-BAN DELAY (Admin Controlled)
                                try:
                                    delay_post = int(db_manager.get_setting('DELAY_POST', 5))
                                except Exception:
                                    delay_post = 5
                                time.sleep(delay_post) 
                            except KeyError as e:
                                print(f"⚠️ Deal data incomplete (missing key: {e}), skip...")
                                continue
                    else:
                        used_keywords.add(final_search_keyword)  # Empty result bhi mark karo taaki repeat na ho
                    
                    # Keywords ke beech chhota delay (anti-ban)
                    if kw_index < len(keywords_to_scrape) - 1:
                        time.sleep(2)
                
                if deals_sent_this_round < 2:
                    current_attempt += 1
                    # 🛑 RETRY DELAY (Admin Controlled)
                    try:
                        delay_retry = int(db_manager.get_setting('DELAY_RETRY', 9))
                    except Exception:
                        delay_retry = 9
                    time.sleep(delay_retry) 
            
            is_live_trend_round = not is_live_trend_round
            round_in_hour += 1 

        except Exception as e:
            print(f"❌ Error: {e}")
            
        # ==========================================
        # ⏰ DYNAMIC TIMING LOGIC (Admin Controlled)
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
            flash_interval = int(db_manager.get_setting('FLASH_INTERVAL', 3))
        except Exception:
            flash_interval = 3

        # 🛡️ HOSTING FIX: Zero division protection
        if flash_interval <= 0:
            flash_interval = 3

        if round_in_hour < 4:
            wait_minutes = round_wait 
            print(f"\n⏳ Round {round_in_hour}/4 complete. Bot agle {wait_minutes} minute tak FLASH SALES track karega...")
        else:
            wait_minutes = long_sleep
            round_in_hour = 0 
            print(f"\n😴 4 Round quota poora! Bot agle {wait_minutes} min tak sirf FLASH SALES dekhega...")

        # 🛡️ HOSTING FIX: Agar wait_minutes somehow 0 ya negative aaye
        if wait_minutes <= 0:
            wait_minutes = 15
            
        # 🟢 THE FLASH SALE LOOP WITH INSTANT STOP
        cycles = (wait_minutes * 60) // 10  # 10 second ke chote gaps
        
        print(f"⏳ Waiting for {wait_minutes} minutes. Checking for Stop signal every 10s...")
        
        for i in range(cycles):
            try:
                # Har 10 second mein check karo ki Admin ne STOP toh nahi dabaya
                if db_manager.get_setting('bot_status', 'ON') == 'OFF':
                    break # Loop se bahar niklo turant
            except Exception:
                pass  # 🛡️ DB error pe loop mat todo
                
            time.sleep(10)
            
            # Har X minute (Admin set) par flash sales check karo
            try:
                if (i * 10) % (flash_interval * 60) == 0 and i != 0:
                    check_flash_sales()
            except Exception as e:
                print(f"⚠️ Flash sale check error in loop: {e}")

if __name__ == "__main__":
    try:
        db_manager.init_db()
    except Exception as e:
        print(f"❌ CRITICAL: Database init fail: {e}")
        print("💡 Check file permissions on the server.")
    
    # 🚨 KOYEB FIX: Dashboard aur Bot ko sath chalane ke liye
    import threading
    from dashboard.app import app
    
    print("🌐 Starting Dashboard on Port 8000...")
    
    # 🛡️ HOSTING FIX: Dashboard crash se bot band nahi hoga
    def start_dashboard():
        try:
            app.run(host='0.0.0.0', port=8000)
        except Exception as e:
            print(f"❌ Dashboard error: {e}")
            print("⚠️ Dashboard band hai lekin Bot chalta rahega!")
            
    threading.Thread(target=start_dashboard, daemon=True).start()
    
    time.sleep(5)
    
    # 🛡️ MASTER SAFETY: Bot kabhi band nahi hoga, chahe koi bhi error aaye
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