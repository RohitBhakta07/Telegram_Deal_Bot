"""
main.py — Deal Hunter Bot (Multi-Channel, Per-Channel Threading)
================================================================
Architecture:
  - Main thread: watches DB every 60s for new/removed channels
  - Per channel: one ChannelBot thread, fully independent state
  - Shared: Logger, db_manager, scraper, affiliate, telegram

What changed from old main.py:
  ✅ get_categories_for_bot(channel_id)    instead of get_all_categories()
  ✅ get_flash_keywords_for_bot(channel_id) instead of get_all_flash_keywords()
  ✅ is_link_already_sent(link, channel_id) per-channel dedup
  ✅ save_deal(..., channel_id)
  ✅ flash_cooldowns keyed per channel (in-memory, reset on restart)
  ✅ send_telegram_message only to that channel's chat_id

What did NOT change (do not touch these files):
  ❌ scraper/flipkart.py
  ❌ analyzer/trends.py
  ❌ telegram/bot.py
  ❌ userbot/extrape_agent.py
  ❌ config.py
  ❌ Affiliate link logic (Plan A → Plan B fallback)
  ❌ Message format
"""

import os
import sys
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import time
import random
import threading
import requests

# ── Path setup ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# ═══════════════════════════════════════════════════════════════════════════
# 1.  MAGIC LOGGER  (same as before — logs to bot.log + terminal)
# ═══════════════════════════════════════════════════════════════════════════
log_file_path = os.path.join(BASE_DIR, 'bot.log')

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log      = open(log_file_path, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()

sys.stdout = Logger()
sys.stderr = Logger()


# ── Imports that need Logger to be active first ───────────────────────────
from analyzer.trends  import get_current_trend, build_flipkart_url
from scraper.flipkart import get_flipkart_deals
from telegram.bot     import send_telegram_message
from config           import EXTRAPE_AFFID, EXTRAPE_PARAM1
from database         import db_manager
from userbot.extrape_agent import get_sync_link


# ═══════════════════════════════════════════════════════════════════════════
# 2.  AFFILIATE LINK  (unchanged Plan A → Plan B logic)
# ═══════════════════════════════════════════════════════════════════════════
def get_affiliate_link(original_url: str) -> str:
    print("🕵️‍♂️ Secret Agent ko link bhej rahe hain...")

    # Plan A: Telegram Userbot (ExtraPe agent)
    try:
        agent_link = get_sync_link(original_url)
        if agent_link and agent_link != original_url:
            print("✅ Agent ne link convert kar diya!")
            return agent_link
        print("⚠️ Agent slow/fail. Plan B chalu...")
    except Exception as e:
        print(f"❌ Agent error: {e}. Plan B chalu...")

    # Plan B: Manual affiliate params + TinyURL
    try:
        affiliate_params = f"&&affid={EXTRAPE_AFFID}&affExtParam1={EXTRAPE_PARAM1}"
        final_long_url   = f"{original_url}{affiliate_params}"
        api_url          = f"http://tinyurl.com/api-create.php?url={final_long_url}"
        response         = requests.get(api_url, timeout=8)
        if response.status_code == 200:
            print("✅ TinyURL affiliate link ready!")
            return response.text
        return final_long_url
    except Exception as e:
        print(f"❌ Affiliate Backup Error: {e}")
        return original_url


# ═══════════════════════════════════════════════════════════════════════════
# 3.  PER-CHANNEL BOT CLASS
# ═══════════════════════════════════════════════════════════════════════════
class ChannelBot(threading.Thread):
    """
    One instance per active Telegram channel.
    Runs its own deal loop + flash tracker independently.
    """

    def __init__(self, channel_id: str, channel_name: str):
        super().__init__(daemon=True, name=f"Bot-{channel_id}")
        self.channel_id   = channel_id
        self.channel_name = channel_name
        self.stop_event   = threading.Event()

        # Per-channel state (same logic as old main.py, just scoped)
        self.round_in_hour      = 0
        self.used_keywords      = set()
        self.is_live_trend_round= True
        self.flash_cooldowns    = {}   # { keyword: last_sent_timestamp }

    def log(self, msg: str):
        """Prefix all logs with channel name for easy reading."""
        print(f"[{self.channel_name}] {msg}")

    def stop(self):
        self.stop_event.set()

    # ── Helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _normalize_link(link: str) -> str:
        """Strip Flipkart tracking/session params so same product = same key."""
        try:
            parsed = urlparse(link)
            # Keep only the path + product-identifying params (pid, lid)
            params = parse_qs(parsed.query)
            keep = {k: v for k, v in params.items()
                    if k.lower() in ('pid', 'lid', 'marketplace', 'q')}
            clean = urlunparse((
                parsed.scheme, parsed.netloc, parsed.path,
                '', urlencode(keep, doseq=True), ''
            ))
            return clean
        except Exception:
            return link

    def _is_link_sent(self, link: str) -> bool:
        normalized = self._normalize_link(link)
        return db_manager.is_link_already_sent(normalized, self.channel_id)

    def _save_deal(self, title, orig_link, aff_link, category):
        normalized = self._normalize_link(orig_link)
        db_manager.save_deal(title, normalized, aff_link, category, self.channel_id)

    def _clear_old_deals(self):
        try:
            total = db_manager.get_total_deals_count(self.channel_id)
            if total >= 192:
                db_manager.clear_all_deals(self.channel_id)
                self.log(f"🧹 Memory reset: {total} deals cleared. New cycle started.")
        except Exception as e:
            self.log(f"⚠️ DB count error: {e}")

    def _send(self, message: str, image_url=None):
        send_telegram_message(message, image_url=image_url, chat_id=self.channel_id)

    # ── Flash Sale Tracker ───────────────────────────────────────────────
    def check_flash_sales(self):
        self.log("⚡ [FLASH] Checking all sniper targets...")

        flash_data = db_manager.get_flash_keywords_for_bot(self.channel_id)
        if not flash_data:
            self.log("⚠️ No flash targets set. Skipping.")
            return

        # Filter out keywords still within 24-hour lock
        current_time    = time.time()
        available       = [
            t for t in flash_data
            if (current_time - self.flash_cooldowns.get(t[1], 0)) > 86400
        ]

        if not available:
            self.log("⏳ All flash targets locked (24h). Skipping.")
            return

        self.log(f"🎯 {len(available)} active target(s). Scanning one by one...")

        for target in available:
            if self.stop_event.is_set():
                return

            flash_keyword   = target[1]
            target_discount = target[2]

            self.log(f"🔍 Scanning: '{flash_keyword.upper()}' (min {target_discount}% off)")

            target_url = build_flipkart_url(flash_keyword, min_discount=target_discount)
            deals      = get_flipkart_deals(target_url, required_discount=target_discount)

            if deals:
                for deal in deals:
                    if self._is_link_sent(deal['link']):
                        continue

                    final_link = get_affiliate_link(deal['link'])

                    message = (
                        f"🚨 <b>MEGA LOOT ALERT | PRICE DROP</b> 🚨\n\n"
                        f"🛍️ {deal['title']}\n\n"
                        f"💰 <b>MRP : </b> <del>{deal['mrp']}</del>\n"
                        f"💸 <b>Loot Price : </b> {deal['price']}\n"
                        f"📉 <b>Flat {deal['discount']}</b>\n\n"
                        f"👉 <b>Loot Fast (Stock ends in mins): 👇</b>\n"
                        f"{final_link}\n\n"
                        f"⚡ <b>Flash Deal:</b> Yeh deal kisi bhi waqt Sold Out ho sakti hai!"
                    )

                    self._send(message, image_url=deal.get('image'))
                    self._save_deal(deal['title'], deal['link'], final_link, "FLASH LOOT")

                    # Lock this keyword for 24 hours
                    self.flash_cooldowns[flash_keyword] = current_time
                    self.log(f"🔒 Keyword locked 24h: '{flash_keyword}'")
                    self.log(f"🚨 FLASH SENT: {deal['title']}")
                    break
            else:
                self.log(f"📉 No flash deal found for '{flash_keyword}'.")

            # Anti-ban delay between keyword scans
            time.sleep(5)

    # ── Main Deal Loop ───────────────────────────────────────────────────
    def run_deal_cycle(self):
        """One full deal-finding round — professional grade."""

        db_categories = db_manager.get_categories_for_bot(self.channel_id)
        if not db_categories:
            self.log("No categories set. Waiting 2 min...")
            time.sleep(120)
            return

        # Build MARKET_DATA dict from DB rows
        MARKET_DATA     = {}
        ALL_KEYWORDS    = set()

        for cat in db_categories:
            cat_name     = cat[1]
            cat_keywords = [k.strip().lower() for k in cat[2].split(',')]
            min_disc     = int(cat[3])
            MARKET_DATA[cat_name] = {
                "keywords"    : cat_keywords,
                "min_discount": min_disc,
            }
            ALL_KEYWORDS.update(cat_keywords)

        # Sync used_keywords against current DB (remove deleted ones)
        self.used_keywords = self.used_keywords.intersection(ALL_KEYWORDS)
        self._clear_old_deals()

        max_attempts            = 3
        deals_sent_this_round   = 0
        sent_links_this_round   = set()    # in-memory link dedup
        sent_titles_this_round  = set()    # in-memory title dedup
        tried_keywords          = set()    # don't re-scrape same keyword

        round_label = "LIVE MARKET TREND" if self.is_live_trend_round else "DATABASE ROTATION"
        self.log(f"\n{'='*50}")
        self.log(f"{round_label} — Round {self.round_in_hour + 1}/4")
        self.log(f"{'='*50}")

        for current_attempt in range(1, max_attempts + 1):
            if deals_sent_this_round >= 2 or self.stop_event.is_set():
                break

            self.log(f"\n--- Attempt {current_attempt}/{max_attempts} ---")

            target_discount   = None
            matched_category  = None
            final_keyword     = ""

            # ── Keyword selection ────────────────────────────────────────
            # Attempt 1 (trend round): use live trend keyword
            # Attempt 2+: always pick a DIFFERENT keyword from DB
            if current_attempt == 1 and self.is_live_trend_round:
                trend = get_current_trend(list(ALL_KEYWORDS))
                self.log(f"Trending: {trend}")
                final_keyword = trend

                for cat_name, data in MARKET_DATA.items():
                    if any(kw in trend for kw in data["keywords"]):
                        target_discount  = data["min_discount"]
                        matched_category = cat_name
                        break

                if matched_category is None:
                    # Trend didn't match any category — pick from remaining
                    remaining = ALL_KEYWORDS - self.used_keywords - tried_keywords
                    if not remaining:
                        self.used_keywords.clear()
                        remaining = ALL_KEYWORDS - tried_keywords
                    if remaining:
                        final_keyword = random.choice(list(remaining))
            else:
                # Pick a keyword that hasn't been tried this round
                remaining = ALL_KEYWORDS - self.used_keywords - tried_keywords
                if not remaining:
                    self.used_keywords.clear()
                    remaining = ALL_KEYWORDS - tried_keywords
                if not remaining:
                    self.log("All keywords exhausted this round. Moving on.")
                    break
                final_keyword = random.choice(list(remaining))
                self.log(f"Keyword: '{final_keyword}'")

            # Don't re-scrape the same keyword
            if final_keyword in tried_keywords:
                self.log(f"Keyword '{final_keyword}' already tried. Skipping.")
                continue
            tried_keywords.add(final_keyword)

            # ── Match keyword to category ────────────────────────────────
            for cat_name, data in MARKET_DATA.items():
                if final_keyword in data["keywords"]:
                    target_discount  = data["min_discount"]
                    matched_category = cat_name
                    break

            if target_discount is None:
                target_discount  = 40
                matched_category = "GENERAL"

            self.log(f"{matched_category.upper()} | min {target_discount}% off")

            # ── Scrape Flipkart ──────────────────────────────────────────
            target_url = build_flipkart_url(final_keyword, min_discount=target_discount)
            deals      = get_flipkart_deals(target_url, required_discount=target_discount)

            if not deals:
                self.log(f"No deals found for '{final_keyword}'.")
                time.sleep(5)
                continue

            found_new = False
            for deal in deals:
                if deals_sent_this_round >= 2:
                    break

                norm_link  = self._normalize_link(deal['link'])
                deal_title = deal.get('title', '').strip()

                # Triple dedup: in-memory link + in-memory title + DB
                if norm_link in sent_links_this_round:
                    continue
                if deal_title and deal_title in sent_titles_this_round:
                    continue
                if self._is_link_sent(deal['link']):
                    self.log(f"Skip (already sent): {deal_title[:50]}")
                    continue

                found_new  = True
                final_link = get_affiliate_link(deal['link'])

                message = (
                    f"🔥 <b>HOT DEAL | Verified ✅</b>\n\n"
                    f"🛍️ {deal_title}\n\n"
                    f"💰 <b>MRP : </b> <del>{deal['mrp']}</del>\n"
                    f"💸 <b>Deal Price : </b> {deal['price']}\n"
                    f"📉 <b>Flat {deal['discount']}</b>\n\n"
                    f"👉 <b>Check price on Flipkart: 👇</b>\n"
                    f"{final_link}\n\n"
                    f"⭐ <b>Rating : </b> {deal['rating']}\n"
                    f"📝 <b>Product Highlights:</b>\n"
                    f"{deal['highlights']}\n"
                    f"⚡ Limited time deal\n"
                    f"⏳ Stock fast finish hota hai!"
                )

                self._send(message, image_url=deal.get('image'))
                self._save_deal(deal_title, deal['link'], final_link, matched_category)
                sent_links_this_round.add(norm_link)
                sent_titles_this_round.add(deal_title)
                self.used_keywords.add(final_keyword)
                deals_sent_this_round += 1
                self.log(f"DEAL SENT ({deals_sent_this_round}/2): {deal_title[:60]}")
                time.sleep(5)

            if not found_new:
                self.log(f"No new deals for '{final_keyword}'. Trying next keyword...")
                time.sleep(5)

        self.log(f"\nRound complete: {deals_sent_this_round} deal(s) sent.")

        # Alternate trend / rotation each round
        self.is_live_trend_round = not self.is_live_trend_round
        self.round_in_hour      += 1

    # ── Thread entry point ───────────────────────────────────────────────
    def run(self):
        self.log(f"🤖 Bot thread started.")

        while not self.stop_event.is_set():
            try:
                self.run_deal_cycle()
            except Exception as e:
                self.log(f"❌ Deal cycle error: {e}")

            # ── Timing: 15 min between rounds, 60 min break after 4 rounds
            if self.round_in_hour < 4:
                wait_minutes = 15
                self.log(f"\n⏳ Round {self.round_in_hour}/4 done. Flash scan every 3 min for {wait_minutes} min...")
            else:
                wait_minutes     = 60
                self.round_in_hour = 0
                self.log(f"\n😴 4/4 rounds done. 60-min rest with flash scanning...")

            # ── Flash scan loop replaces sleep ───────────────────────────
            total_cycles = wait_minutes // 3      # 5 cycles for 15-min, 20 for 60-min
            for _ in range(total_cycles):
                if self.stop_event.is_set():
                    return
                time.sleep(3 * 60)               # sleep 3 minutes
                try:
                    self.check_flash_sales()
                except Exception as e:
                    self.log(f"❌ Flash check error: {e}")

        self.log("🛑 Bot thread stopped.")


# ═══════════════════════════════════════════════════════════════════════════
# 4.  CHANNEL MANAGER  (main thread — watches for channel changes)
# ═══════════════════════════════════════════════════════════════════════════
class ChannelManager:
    """
    Runs in the main thread.
    Every 60 seconds it checks which channels are active in the DB.
    Starts new ChannelBot threads for new channels.
    Stops ChannelBot threads for deleted/paused channels.
    """

    def __init__(self):
        self.bots: dict[str, ChannelBot] = {}  # channel_id → ChannelBot instance

    def _get_active_channel_ids(self) -> dict:
        """Returns {channel_id: channel_name} for all active channels."""
        try:
            channels = db_manager.get_all_channels()
            return {
                ch['channel_id']: ch['channel_name']
                for ch in channels
                if ch.get('is_active', 1) == 1
            }
        except Exception as e:
            print(f"❌ ChannelManager DB error: {e}")
            return {}

    def sync(self):
        """Start bots for new channels, stop bots for removed/paused channels."""
        active = self._get_active_channel_ids()
        current_ids = set(self.bots.keys())
        active_ids  = set(active.keys())

        # ── Start new channels ───────────────────────────────────────────
        for cid in active_ids - current_ids:
            name = active[cid]
            print(f"\n🚀 Starting bot for new channel: {name} ({cid})")
            bot = ChannelBot(channel_id=cid, channel_name=name)
            bot.start()
            self.bots[cid] = bot

        # ── Stop removed / paused channels ──────────────────────────────
        for cid in current_ids - active_ids:
            name = self.bots[cid].channel_name
            print(f"\n🛑 Stopping bot for removed/paused channel: {name} ({cid})")
            self.bots[cid].stop()
            del self.bots[cid]

    def run(self):
        print("\n" + "="*60)
        print("🤖  DEAL HUNTER BOT  —  Multi-Channel Mode")
        print("="*60)
        print("📡 Watching DB for channels. Starting threads...\n")

        while True:
            try:
                self.sync()

                active_count = len(self.bots)
                if active_count == 0:
                    print("⚠️  No active channels in DB. Add channels via Super Admin panel.")
                else:
                    print(f"📊 Active bots: {active_count} | "
                          f"Channels: {[b.channel_name for b in self.bots.values()]}")

            except Exception as e:
                print(f"❌ ChannelManager sync error: {e}")

            # Check for new/removed channels every 60 seconds
            time.sleep(60)


# ═══════════════════════════════════════════════════════════════════════════
# 5.  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Init / migrate DB on startup
    db_manager.init_db()

    # Small delay to let DB settle
    time.sleep(2)

    # Start the channel manager (blocks forever)
    manager = ChannelManager()
    manager.run()