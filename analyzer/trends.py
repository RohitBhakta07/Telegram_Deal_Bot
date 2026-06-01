import urllib.parse
import random
import time
from pytrends.request import TrendReq

# ==========================================
# 🧠 SMART CACHING & MEMORY VARIABLES
# ==========================================
CACHE_DURATION = 6 * 60 * 60  # 6 Ghante tak Google ko pareshan nahi karega
last_fetch_time = 0
cached_matched_products = []

# Pichle bheje gaye products ki history (Taki repeat na hon)
recent_history = []
# ==========================================

def get_current_trend(vip_products_list):
    """
    Google Trends API + Smart Caching + Anti-Ban (User-Agent) + Memory Filter
    """
    global last_fetch_time, cached_matched_products, recent_history
    current_time = time.time()
    
    # 🟢 STEP 1 (Cache Check): Agar 6 ghante nahi hue hain, toh Google ke paas mat jao
    if (current_time - last_fetch_time) < CACHE_DURATION and cached_matched_products:
        print("⚡ CACHE se trend nikal rahe hain (API bacha rahe hain)...")
        options = cached_matched_products
    else:
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
            
            if matched_products:
                # Naye data ko Cache mein save kar lo
                cached_matched_products = matched_products
                last_fetch_time = current_time
                options = matched_products
            else:
                options = vip_products_list
                
        except Exception as e:
            print(f"⚠️ Google Trends Error (Ignore it): {e}")
            if cached_matched_products:
                options = cached_matched_products
            else:
                options = vip_products_list

    # 🟢 STEP 2 (REPEAT ROKNE KA LOGIC): History check karo
    available_options = [p for p in options if p not in recent_history]
    
    # Agar saare options history mein aa chuke hain, toh history clear kar do
    if not available_options:
        recent_history.clear()
        available_options = options
        
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
