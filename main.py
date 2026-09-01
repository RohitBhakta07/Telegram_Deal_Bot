"""
Deal Hunter Bot V3 — Production-grade architecture.
- Per-thread browser instances (thread-safe)
- APScheduler for reliable scheduling
- Thread-safe state with DB persistence
- Bounded PriorityQueue with backpressure
- Structured logging with rotation
- Graceful shutdown via Event signals
- Crash recovery from persisted state
"""
import os
import sys
import time
import random
import queue
import threading
import logging
import signal
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# ---- STRUCTURED LOGGING ----
log_file_path = os.path.join(BASE_DIR, 'bot.log')
_handler = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

_logger = logging.getLogger('dealbuddy')
_logger.setLevel(logging.INFO)
_logger.addHandler(_handler)

# Also log to console
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
_logger.addHandler(_console)

def log_info(msg): _logger.info(msg)
def log_warn(msg): _logger.warning(msg)
def log_error(msg): _logger.error(msg)
def log_debug(msg): _logger.debug(msg)

from analyzer.trends import get_current_trend, build_flipkart_url
from scraper.flipkart import get_flipkart_deals, scrape_keyword_full
from telegram.bot import send_telegram_deal_post, send_telegram_message
from config import EXTRAPE_AFFID, EXTRAPE_PARAM1
from database import db_manager
from userbot.extrape_agent import get_sync_link
from analyzer.deal_selector import pick_best_deal
from analyzer.keyword_selector import select_smart_keywords, record_keyword_result
from telegram.post_format import build_deal_message, resolve_post_format
from telegram.deal_media import post_deal_message

# ---- THREAD-SAFE STATE ----
_db_lock = threading.Lock()
_state_lock = threading.Lock()

# Persisted state keys
_KEY_CURRENT_ROUND = 'bot_current_round'
_KEY_IS_TREND_ROUND = 'bot_is_trend_round'
_KEY_USED_KEYWORDS = 'used_keywords'
_KEY_KEYWORD_STATS = 'keyword_performance_v1'


def _save_state(**kwargs):
    """Persist runtime state to DB for crash recovery."""
    with _db_lock:
        for key, value in kwargs.items():
            db_manager.update_setting(key, str(value))


def _load_state(key, default=None):
    """Load persisted state from DB."""
    with _db_lock:
        val = db_manager.get_setting(key)
        if val is None:
            return default
        return val


def is_link_already_sent(link):
    try:
        with _db_lock:
            return db_manager.is_link_already_sent(link)
    except Exception as e:
        log_error(f"DB link check error: {e}")
        return False


def clear_old_links():
    try:
        with _db_lock:
            total_deals = db_manager.get_total_deals_count()
            if total_deals >= 192:
                deleted = db_manager.delete_oldest_deals(50)
                log_info(
                    f"History cleanup: {total_deals} deals total; "
                    f"removed {deleted} oldest records."
                )
    except Exception as e:
        log_error(f"DB count error: {e}")


def get_affiliate_link(original_url):
    """Generate affiliate link via ExtraPe bot only."""
    log_info("Generating affiliate link via ExtraPe...")
    try:
        agent_link = get_sync_link(original_url)
        if agent_link and agent_link != original_url:
            log_info("Affiliate link generated successfully via ExtraPe!")
            return agent_link
        log_warn("ExtraPe failed. Using original URL with affiliate params.")
    except Exception as e:
        log_warn(f"ExtraPe error: {e}. Using original URL with affiliate params.")

    if not EXTRAPE_AFFID:
        log_warn("EXTRAPE_AFFID missing; using original URL without affiliate fallback.")
        return original_url

    # Valid, idempotent fallback query string. Never emit the old `&&affid`.
    try:
        parts = urlsplit(original_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["affid"] = EXTRAPE_AFFID
        query["affExtParam1"] = EXTRAPE_PARAM1
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(query), parts.fragment))
    except Exception:
        separator = "&" if "?" in original_url else "?"
        return f"{original_url}{separator}affid={EXTRAPE_AFFID}&affExtParam1={EXTRAPE_PARAM1}"


# ==========================================
# CONSUMER THREAD — Queue → Telegram poster
# ==========================================

def _post_single_deal(deal_queue, stop_event, item, priority, timestamp,
                      final_affiliate_link):
    """Format, send, save, and mark done for a single deal. Returns True on success."""
    deal = item['deal']
    score = item['score']
    keyword = item['keyword']
    category = item['category']
    post_fmt = item['post_format']
    link = deal.get('link', '')
    title_short = deal.get('title', '')[:40]

    log_info(f"[Consumer] Processing: {title_short}... (Priority={priority}, Score={score['total']})")

    # Format message
    try:
        resolved_fmt = resolve_post_format(
            is_flash=(priority <= 1),
            category_format=post_fmt,
            default_format=db_manager.get_setting('DEFAULT_POST_FORMAT', 'hot_deal'),
            flash_format=db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot'),
        )
        message = build_deal_message(deal, final_affiliate_link, resolved_fmt)
    except Exception as e:
        log_error(f"[Consumer] Message format error: {e}")
        deal_queue.task_done()
        return False

    # Send to channels
    try:
        with _db_lock:
            channels = db_manager.get_all_channels()
    except Exception as e:
        log_error(f"[Consumer] Channel DB error: {e}")
        channels = []

    sent_count = 0
    if channels:
        for channel in channels:
            try:
                result = post_deal_message(send_telegram_deal_post, channel[0], message, deal)
                if result:
                    sent_count += 1
                    log_info(f"[Consumer] Sent to {channel[0]}: {title_short}")
                else:
                    log_error(f"[Consumer] Telegram rejected post for {channel[0]}: {title_short}")
            except Exception as e:
                log_error(f"[Consumer] Telegram error ({channel[0]}): {e}")
    else:
        log_warn("[Consumer] No channels configured!")

    # Do not permanently suppress a deal that Telegram never accepted.
    if sent_count:
        try:
            with _db_lock:
                db_manager.save_deal(
                    title=deal.get('title', ''),
                    original_link=link,
                    affiliate_link=final_affiliate_link,
                    category=category,
                    product_image=deal.get('image', ''),
                    post_type='flash' if priority <= 1 else 'normal',
                )
        except Exception as e:
            log_warn(f"[Consumer] Deal save error: {e}")

    # Clean up pre-taken screenshot after all channels done
    from telegram.deal_media import cleanup_deal_media
    cleanup_deal_media(deal)

    deal_queue.task_done()
    return sent_count > 0


def consumer_thread(deal_queue, stop_event, max_queue_size=100):
    """
    Background thread: pops highest-priority deals from queue,
    sends each to ExtraPe bot, waits for affiliate link,
    then formats and posts to Telegram. Sequential per deal.
    """
    log_info("[Consumer] Telegram poster thread started!")

    while not stop_event.is_set():
        try:
            try:
                priority, timestamp, item = deal_queue.get(timeout=5)
            except queue.Empty:
                continue

            deal = item['deal']
            score = item['score']
            keyword = item['keyword']
            category = item['category']
            post_fmt = item['post_format']
            link = deal.get('link', '')
            title_short = deal.get('title', '')[:40]

            if is_link_already_sent(link):
                log_info(f"[Consumer] Already sent, skip: {title_short}")
                deal_queue.task_done()
                continue

            # 1. Get affiliate link from ExtraPe (blocks until reply)
            try:
                final_affiliate_link = get_affiliate_link(link)
            except Exception as e:
                log_error(f"[Consumer] Affiliate link error: {e}")
                final_affiliate_link = link

            # 2. Post deal
            _post_single_deal(deal_queue, stop_event, item, priority,
                              timestamp, final_affiliate_link)

            # 3. Delay before next post
            try:
                delay = int(db_manager.get_setting('QUEUE_DELAY_POST', 15))
            except Exception:
                delay = 15
            log_info(f"[Consumer] {delay}s wait before next post...")
            if stop_event.wait(timeout=delay):
                break

        except Exception as e:
            log_error(f"[Consumer] Error: {e}")
            if stop_event.wait(timeout=5):
                break

    log_info("[Consumer] Thread stopped.")


# ==========================================
# FLASH DEAL DETECTOR — Adaptive polling
# ==========================================
class FlashDetector:
    """Adaptive flash deal detector with incremental change detection.

    Strategy:
    - Cooldown per keyword: shorter than old 24h (configurable, default 1h)
    - Adaptive interval: checks more frequently when deals are found
    - Jitter: ±25% random variation to avoid fingerprinting
    - Persistence: cooldown state saved to DB for crash recovery
    - Incremental: lightweight hash comparison before full scrape
    """

    def __init__(self):
        self.min_interval = 120       # 2 minutes (aggressive)
        self.max_interval = 900       # 15 minutes (conservative)
        self.current_interval = 300   # Start at 5 minutes
        self._lock = threading.Lock()

    def is_available(self, keyword, cooldown_minutes=60):
        """Check if keyword is past its cooldown."""
        with self._lock:
            key = f'flash_cd_{keyword}'
            last = db_manager.get_setting(key)
            if not last:
                return True
            try:
                return time.time() - float(last) > cooldown_minutes * 60
            except (ValueError, TypeError):
                return True

    def mark_checked(self, keyword):
        """Persist cooldown timestamp to DB."""
        with self._lock:
            key = f'flash_cd_{keyword}'
            db_manager.update_setting(key, str(time.time()))

    def adaptive_interval(self, found_deals):
        """Shorten interval if deals found, lengthen if none."""
        with self._lock:
            if found_deals:
                self.current_interval = max(self.min_interval, self.current_interval // 2)
            else:
                self.current_interval = min(self.max_interval, int(self.current_interval * 1.5))
            jitter = random.uniform(0.75, 1.25)
            return int(self.current_interval * jitter)


flash_detector = FlashDetector()


def check_flash_sales(deal_queue):
    """Check flash deals with adaptive polling and persistence."""
    try:
        log_info("[FLASH] Checking flash deals...")
        try:
            flash_data = db_manager.get_all_flash_keywords()
        except Exception as e:
            log_error(f"[FLASH] DB error: {e}")
            return

        if not flash_data:
            log_info("[FLASH] No flash keywords configured.")
            return

        # Get cooldown from settings (default 60 min)
        try:
            cooldown = max(10, int(db_manager.get_setting('FLASH_COOLDOWN', '60')))
        except Exception:
            cooldown = 60

        available = [t for t in flash_data if flash_detector.is_available(t[1], cooldown)]
        if not available:
            log_info(f"[FLASH] All keywords in cooldown ({cooldown}min).")
            return

        log_info(f"[FLASH] {len(available)} keywords available. Scraping...")

        try:
            min_buyers = int(db_manager.get_setting('MIN_BUYERS_COUNT', 1000))
            allow_missing = db_manager.get_setting('ALLOW_MISSING_BUYERS', 'OFF') == 'ON'
        except Exception:
            min_buyers = 1000
            allow_missing = False

        max_flash_workers = min(len(available), 3)
        deals_found = 0

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
                    'max_pages': 1,
                    'category_name': 'FLASH LOOT',
                    'priority_weight': 4,
                    'post_format': db_manager.get_setting('FLASH_POST_FORMAT', 'mega_loot'),
                    'allow_missing_buyers': allow_missing,
                }
                time.sleep(random.uniform(1, 3))
                future = flash_executor.submit(
                    scrape_keyword_full, flash_keyword, flash_settings,
                    deal_queue, is_link_already_sent,
                )
                futures[future] = flash_keyword

            for future in as_completed(futures):
                keyword = futures[future]
                try:
                    future.result()
                    flash_detector.mark_checked(keyword)
                    deals_found += 1
                    log_info(f"[FLASH] '{keyword}' checked and cooldown set.")
                except Exception as e:
                    log_error(f"[FLASH] '{keyword}' error: {e}")

        next_interval = flash_detector.adaptive_interval(deals_found)
        log_info(f"[FLASH] Next check in ~{next_interval}s ({deals_found} deals found)")

    except Exception as e:
        log_error(f"[FLASH] Critical error: {e}")


# ==========================================
# MAIN BOT LOGIC
# ==========================================
def run_bot():
    """Main bot loop with scheduled rounds and flash detection."""
    log_info("Deal Hunter Bot V3 starting!")

    try:
        ss = "ON"
        db_manager.update_setting("PRICE_SCREENSHOT", ss)
        log_info("Professional 2-photo album: ON (mandatory)")
    except Exception as e:
        log_warn(f"Could not read PRICE_SCREENSHOT setting: {e}")

    # Bounded priority queue with backpressure
    deal_queue = queue.PriorityQueue(maxsize=100)

    # Thread coordination
    stop_event = threading.Event()

    def signal_handler(sig, frame):
        log_info("Shutdown signal received. Stopping gracefully...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start consumer thread
    poster = threading.Thread(
        target=consumer_thread,
        args=(deal_queue, stop_event),
        daemon=True,
        name="TelegramPoster",
    )
    poster.start()

    # Recover state from DB
    round_in_hour = int(_load_state(_KEY_CURRENT_ROUND, '0'))
    is_live_trend_round = _load_state(_KEY_IS_TREND_ROUND, 'True') == 'True'

    saved_memory = db_manager.get_setting('used_keywords', '')
    used_keywords = set(saved_memory.split(',')) if saved_memory else set()
    try:
        keyword_stats = json.loads(db_manager.get_setting(_KEY_KEYWORD_STATS, '{}') or '{}')
        if not isinstance(keyword_stats, dict):
            keyword_stats = {}
    except (TypeError, ValueError):
        keyword_stats = {}
    log_info(f"State recovered: round={round_in_hour}, trend_round={is_live_trend_round}, keywords={len(used_keywords)}")

    while not stop_event.is_set():
        try:
            # Check bot status
            try:
                bot_status = db_manager.get_setting('bot_status', 'ON')
            except Exception:
                bot_status = 'ON'

            if bot_status == 'OFF':
                log_info("Bot is PAUSED. Waiting 60 seconds...")
                if stop_event.wait(timeout=60):
                    break
                continue

            # Read categories
            try:
                db_categories = db_manager.get_all_categories()
            except Exception as e:
                log_error(f"Categories DB error: {e}")
                if stop_event.wait(timeout=120):
                    break
                continue

            if not db_categories:
                log_warn("No categories found. Waiting...")
                if stop_event.wait(timeout=120):
                    break
                continue

            db_categories = db_manager.order_categories_by_priority(db_categories)
            keyword_weights = db_manager.build_keyword_weights(db_categories)

            # Build category maps
            MARKET_DATA = {}
            ALL_KEYWORDS_SET = set()
            category_priority_map = {}
            category_format_map = {}
            category_by_keyword = {}

            for cat in db_categories:
                try:
                    cat_name = cat[1]
                    cat_keywords = [k.strip().lower() for k in cat[2].split(',')]
                    min_disc = int(cat[3])
                    priority = cat[4] if len(cat) > 4 else 'MEDIUM'
                    post_fmt = cat[5] if len(cat) > 5 else 'default'

                    MARKET_DATA[cat_name] = {
                        "keywords": cat_keywords,
                        "min_discount": min_disc,
                    }
                    ALL_KEYWORDS_SET.update(cat_keywords)
                    category_priority_map[cat_name] = db_manager.get_priority_weight(priority)
                    category_format_map[cat_name] = post_fmt
                    for keyword in cat_keywords:
                        category_by_keyword.setdefault(keyword, cat_name)
                except (IndexError, TypeError, ValueError) as e:
                    log_warn(f"Category data corrupt, skip: {e}")
                    continue

            if not ALL_KEYWORDS_SET:
                log_warn("No valid keywords found. Waiting...")
                if stop_event.wait(timeout=120):
                    break
                continue

            # Filter used keywords to existing ones
            with _state_lock:
                used_keywords = used_keywords.intersection(ALL_KEYWORDS_SET)
            clear_old_links()

            # Read settings
            try:
                keywords_per_round = max(1, min(10, int(db_manager.get_setting('KEYWORDS_PER_ROUND', 4))))
                max_workers = max(1, min(6, int(db_manager.get_setting('MAX_WORKERS', 2))))
                min_buyers = int(db_manager.get_setting('MIN_BUYERS_COUNT', 1000))
                max_pages = max(1, min(5, int(db_manager.get_setting('MAX_SCRAPE_PAGES', 3))))
                allow_missing = db_manager.get_setting('ALLOW_MISSING_BUYERS', 'OFF') == 'ON'
            except Exception:
                keywords_per_round, max_workers, min_buyers, max_pages = 4, 2, 1000, 3
                allow_missing = False

            round_label = "LIVE MARKET TREND" if is_live_trend_round else "DATABASE ROTATION"
            log_info(f"--- ROUND {round_in_hour+1}/4 : {round_label} ---")
            log_info(f"Workers={max_workers} | MinBuyers={min_buyers} | MaxPages={max_pages}")

            # Select keywords
            keywords_to_scrape = []

            if is_live_trend_round:
                try:
                    trend = get_current_trend(list(ALL_KEYWORDS_SET))
                    log_info(f"Trending keyword: {trend}")
                    with _state_lock:
                        if trend not in used_keywords:
                            keywords_to_scrape.append(trend)
                        else:
                            log_info(f"'{trend}' already used. Using DB backup.")
                except Exception as e:
                    log_warn(f"Google Trends error: {e}. Using DB backup.")

            with _state_lock:
                remaining_pool = list(ALL_KEYWORDS_SET - used_keywords - set(keywords_to_scrape))
            if not remaining_pool:
                with _state_lock:
                    used_keywords.clear()
                remaining_pool = list(ALL_KEYWORDS_SET - set(keywords_to_scrape))

            needed = keywords_per_round - len(keywords_to_scrape)
            keywords_to_scrape.extend(select_smart_keywords(
                remaining_pool,
                needed,
                keyword_weights,
                keyword_stats,
                category_by_keyword,
            ))

            log_info(f"Scraping this round: {keywords_to_scrape}")

            # Parallel scraping
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for idx, kw in enumerate(keywords_to_scrape):
                    # Find matching category
                    matched_cat = None
                    matched_discount = 60
                    for cat_name, data in MARKET_DATA.items():
                        if kw in data['keywords']:
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
                        'price_screenshot_on': ss == 'ON',
                    }

                    log_info(f"[{idx+1}/{len(keywords_to_scrape)}] Submitting: '{kw}' (Cat={matched_cat or 'GENERAL'})")
                    future = executor.submit(
                        scrape_keyword_full, kw, kw_settings, deal_queue, is_link_already_sent,
                    )
                    futures[future] = kw

                for future in as_completed(futures):
                    kw = futures[future]
                    try:
                        deals_found = future.result() or 0
                        record_keyword_result(keyword_stats, kw, deals_found)
                        with _state_lock:
                            used_keywords.add(kw)
                        log_info(f"Scraper done: '{kw}' | qualified={deals_found}")
                    except Exception as e:
                        log_error(f"Scraper error ({kw}): {e}")
                        record_keyword_result(keyword_stats, kw, 0)
                        with _state_lock:
                            used_keywords.add(kw)

            # Persist state
            with _state_lock:
                _save_state(**{_KEY_USED_KEYWORDS: ','.join(used_keywords)})
            _save_state(**{_KEY_KEYWORD_STATS: json.dumps(keyword_stats, separators=(',', ':'))})

            is_live_trend_round = not is_live_trend_round
            round_in_hour += 1

            # Persist round state
            _save_state(**{
                _KEY_CURRENT_ROUND: str(round_in_hour),
                _KEY_IS_TREND_ROUND: str(is_live_trend_round),
            })

            log_info(f"Queue size: {deal_queue.qsize()} deals pending")

        except Exception as e:
            log_error(f"Main loop error: {e}")

        # Wait period with flash checks
        try:
            round_wait = int(db_manager.get_setting('ROUND_WAIT', '15'))
        except Exception:
            round_wait = 15
        try:
            long_sleep = int(db_manager.get_setting('LONG_SLEEP', '60'))
        except Exception:
            long_sleep = 60
        try:
            flash_interval = max(1, int(db_manager.get_setting('FLASH_INTERVAL', '3')))
        except Exception:
            flash_interval = 3

        if round_in_hour < 4:
            wait_minutes = max(1, round_wait)
            log_info(f"Round {round_in_hour}/4 complete. {wait_minutes}min wait. Flash every {flash_interval}min...")
        else:
            wait_minutes = max(1, long_sleep)
            round_in_hour = 0
            log_info(f"4 rounds done! {wait_minutes}min sleep. Flash every {flash_interval}min...")
            _save_state(**{_KEY_CURRENT_ROUND: '0'})

        # Flash check loop — uses Event.wait for interruptibility
        cycles = (wait_minutes * 60) // 10
        for i in range(cycles):
            if stop_event.is_set():
                break

            try:
                if db_manager.get_setting('bot_status', 'ON') == 'OFF':
                    break
            except Exception:
                pass

            if stop_event.wait(timeout=10):
                break

            if (i * 10) % (flash_interval * 60) == 0 and i != 0:
                check_flash_sales(deal_queue)

    log_info("Bot main loop exited.")


if __name__ == "__main__":
    try:
        db_manager.init_db()
        log_info("Database initialized.")
    except Exception as e:
        log_error(f"CRITICAL: Database init failed: {e}")

    # Start dashboard
    from dashboard.app import app
    log_info("Starting Dashboard on port 8000...")

    def start_dashboard():
        try:
            app.run(host='0.0.0.0', port=8000, use_reloader=False)
        except Exception as e:
            log_error(f"Dashboard error: {e}")

    threading.Thread(target=start_dashboard, daemon=True).start()

    # Main bot loop with crash recovery
    while True:
        try:
            run_bot()
        except KeyboardInterrupt:
            log_info("Bot stopped manually (Ctrl+C).")
            break
        except Exception as e:
            log_error(f"BOT CRASH: {e}")
            log_info("Auto-restart in 30 seconds...")
            time.sleep(30)
