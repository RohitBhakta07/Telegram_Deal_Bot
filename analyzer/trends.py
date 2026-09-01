import urllib.parse
import random
import time
import threading
from pytrends.request import TrendReq

# ==========================================
# 🧠 SMART CACHING & MEMORY VARIABLES
# ==========================================
CACHE_DURATION = 6 * 60 * 60      # 6 Ghante normal cache
COOLDOWN_AFTER_429 = 2 * 60 * 60  # 2 Ghante cooldown after rate limit
last_fetch_time = 0
cached_matched_products = []
_rate_limited_until = 0  # Timestamp until which we skip API calls

# Pichle bheje gaye products ki history (Taki repeat na hon)
recent_history = []

# 🛡️ SECURITY: Thread-safe lock for all cache access (multiple scrapers can call this in parallel)
_trends_lock = threading.Lock()
# ==========================================

def get_current_trend(vip_products_list):
    """
    Google Trends API + Smart Caching + Anti-Ban (User-Agent) + Memory Filter
    Thread-safe — uses _trends_lock to prevent race conditions when multiple scrapers call in parallel.
    On 429 rate limit, sets a 2-hour cooldown to avoid getting blocked permanently.
    """
    global last_fetch_time, cached_matched_products, recent_history, _rate_limited_until
    current_time = time.time()

    # 🟢 STEP 1 (Cache + Rate Limit Check)
    with _trends_lock:
        # If we're in cooldown from a 429, skip API entirely
        if current_time < _rate_limited_until:
            if cached_matched_products:
                print("⏳ Google Trends rate-limited. Using cache (cooldown active)...")
                options = list(cached_matched_products)
                _cached_result = True
            else:
                print("⏳ Google Trends rate-limited. Using DB pool...")
                options = list(vip_products_list)
                _cached_result = True
        elif (current_time - last_fetch_time) < CACHE_DURATION and cached_matched_products:
            print("⚡ CACHE se trend nikal rahe hain (API bacha rahe hain)...")
            options = list(cached_matched_products)
            _cached_result = True
        else:
            _cached_result = False

    if not _cached_result:
        print("🌐 Google Trends se NAYA LIVE Market Data nikal rahe hain...")
        matched_products = []
        try:
            # 🟢 ANTI-BAN LOGIC: Bhesh badalna (Browser Spoofing)
            custom_header = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            }
            pytrend = TrendReq(hl='en-IN', tz=330, requests_args={'headers': custom_header})

            kw_list = ['flipkart']
            pytrend.build_payload(kw_list, geo='IN', timeframe='now 1-d')
            related_data = pytrend.related_queries()
            live_trends_list = []

            if related_data and 'flipkart' in related_data and related_data['flipkart'].get('rising') is not None:
                trends = related_data['flipkart']['rising']['query'].tolist()
                for t in trends[:15]:
                    clean_trend = str(t).replace('flipkart', '').strip().lower()
                    if len(clean_trend) > 2:
                        live_trends_list.append(clean_trend)

            if live_trends_list:
                for live_trend in live_trends_list:
                    for vip_product in vip_products_list:
                        if vip_product.lower() in live_trend:
                            matched_products.append(vip_product)

            with _trends_lock:
                if matched_products:
                    cached_matched_products = list(matched_products)
                    last_fetch_time = current_time
                    options = matched_products
                else:
                    options = list(vip_products_list)

        except Exception as e:
            err_str = str(e)
            # 🛡️ 429 rate limit — set cooldown so we don't hammer Google
            if '429' in err_str or 'Too Many Requests' in err_str:
                with _trends_lock:
                    _rate_limited_until = current_time + COOLDOWN_AFTER_429
                    if last_fetch_time == 0:
                        last_fetch_time = current_time  # Prevent immediate retry
                print(f"⚠️ Google Trends RATE LIMITED (429). Cooling down for 2 hours.")
            else:
                print(f"⚠️ Google Trends Error (Ignore it): {e}")

            with _trends_lock:
                if cached_matched_products:
                    options = list(cached_matched_products)
                else:
                    options = list(vip_products_list)

    # 🟢 STEP 2 (REPEAT ROKNE KA LOGIC): History check karo
    with _trends_lock:
        available_options = [p for p in options if p not in recent_history]

        # Agar saare options history mein aa chuke hain, toh history clear kar do
        if not available_options:
            recent_history.clear()
            available_options = list(options)

        selected_trend = random.choice(available_options)

        # History mein is naye trend ko add karo
        recent_history.append(selected_trend)
        if len(recent_history) > 5: # Sirf pichle 5 yaad rakho
            recent_history.pop(0)

    print(f"📈 Final Trend Pakda: '{selected_trend}'")
    return selected_trend

def build_flipkart_url(keyword, min_discount=60, page=1):
    """
    Keyword aur discount ko milakar Flipkart ka search link banata hai.
    page parameter se Page 2, 3 etc. par ja sakte hain (retry loop ke liye).
    """
    encoded_keyword = urllib.parse.quote_plus(keyword)
    url = f"https://www.flipkart.com/search?q={encoded_keyword}&p%5B%5D=facets.discount_range_v1%255B%255D%3D{min_discount}%2525%2Bmore&page={page}"
    return url
