# scraper.py
from playwright.sync_api import sync_playwright
import time
import re

def get_flipkart_deals(search_url, required_discount=60):
    deals = []
    
    print("🔍 Opening chrome Browser...")
    with sync_playwright() as p:

        # 🚀 HOSTING UPGRADE: Linux server ke liye special arguments taaki crash na ho
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", 
                "--disable-setuid-sandbox", 
                "--disable-dev-shm-usage"
            ]
        ) 
        
        # 🛡️ ANTI-BAN UPGRADE: Flipkart ko lagega ki koi asli insaan Windows PC se chala raha hai
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        print("🌐 Flipkart par jaa rahe hain...")
        # Timeout thoda zyada rakha hai taaki slow internet par bhi load ho jaye
        page.goto(search_url, timeout=60000)
        
        # Page ko thoda neeche scroll karenge taaki saare products load ho jayein
        print("⏬ Page scroll kar rahe hain...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3) # 3 second wait
        
        print("📦 Products extract kar rahe hain...\n")
        
        # Flipkart ke products usually 'div[data-id]' tag ke andar hote hain
        product_cards = page.locator("div[data-id]").all()
        
        # Hum top 5 products nikalenge
        for card in product_cards[:6]:
            try:
                card_text_full = card.inner_text().lower() # Sab kuch chota (lower) kar diya searching ke liye
                oos_keywords = ["out of stock", "sold out", "currently unavailable", "temporarily unavailable","cheak address"]
                is_oos = False
                for keyword in oos_keywords:
                    if keyword in card_text_full:
                        is_oos = True
                        break
                
                if is_oos:
                    print("🚫 Skip Kiya: Product OUT OF STOCK hai!")
                    continue # Seedha agle product par chalo
                # ==========================================
                link_element = card.locator("a").first
                full_link = f"https://www.flipkart.com{link_element.get_attribute('href')}"
                
                card_text = card.inner_text().split('\n')
                
                # Naya Pro Feature: 'Ad' ya 'Sponsored' text ko title banne se rokna
                title = "Trending Product"
                for t_line in card_text:
                    clean_line = t_line.strip().lower()
                    if clean_line and clean_line not in ["ad", "sponsored", "bestseller"]:
                        title = t_line.strip()
                        break
                
                # 📸 SMART IMAGE EXTRACTOR (Sirf asli photo nikalega, kachra nahi)
                image_url = ""
                try:
                    images = card.locator("img").all()
                    for img in images:
                        src = img.get_attribute("src")
                        # Flipkart ke asli image link mein 'http' aur 'rukminim' (unka server) likha hota hai
                        if src and src.startswith("http") and "rukminim" in src:
                            image_url = src
                            break
                        elif src and src.startswith("http"):
                            image_url = src 
                except Exception as e:
                    print(f"Image Error: {e}")

                deal_info = {
                    "title": title[:50] + "...", 
                    "link": full_link,
                    "image": image_url,
                    "price": "Check Link", 
                    "mrp": "Check Link",
                    "discount": "0",  
                    "rating": "0.0",  
                    "highlights": "" 
                }
                
                # 1. Highlights Logic
                highlight_elements = card.locator("li").all()
                highlights_list = []
                for el in highlight_elements[:4]:
                    text = el.inner_text().strip()
                    if text:
                        highlights_list.append(f"🔹 {text}")
                
                if not highlights_list:
                    brand_name = card_text[0] if len(card_text) > 0 else "Top Brand"
                    if brand_name.lower() in ["ad", "sponsored", "bestseller"]:
                        brand_name = card_text[1] if len(card_text) > 1 else "Top Brand"
                    deal_info["highlights"] = f"🔹 Brand: {brand_name}\n🔹 100% Original Product\n🔹 Best Quality & Comfort"
                else:
                    deal_info["highlights"] = "\n".join(highlights_list)

                # 🕵️‍♂️ 2. UNIVERSAL PRICE & DISCOUNT LOGIC (Bulletproof Fix)

                # STEP A: Pehle Discount nikal kar original text se usko 'Mita' (Remove) do
                discount_match = re.search(r'(\d{1,2})\s*%', card.inner_text())
                if discount_match:
                    deal_info["discount"] = discount_match.group(1)
                    # Text se % wala hissa space se replace kar rahe hain taaki "122333" mix na ho
                    safe_text = re.sub(r'\d{1,2}\s*%', ' ', card.inner_text())
                else:
                    safe_text = card.inner_text()

                # STEP B: Ab us 'safe' text se Prices nikalenge
                prices_str = re.findall(r'₹\s*([\d,]+)', safe_text)
                valid_prices = []
                for p in prices_str:
                    try:
                        # Comma hata kar sahi number (integer) banayenge
                        valid_prices.append(int(p.replace(',', '')))
                    except:
                        pass
                
                # STEP C: Hamesha Bada number MRP banega aur chota number Deal Price
                if len(valid_prices) >= 2:
                    valid_prices.sort(reverse=True) # Sort karega (bada pehle)
                    deal_info["mrp"] = f"₹{valid_prices[0]:,}"
                    deal_info["price"] = f"₹{valid_prices[1]:,}"
                elif len(valid_prices) == 1:
                    deal_info["price"] = f"₹{valid_prices[0]:,}"
                    deal_info["mrp"] = "Check Link"

                # 🌟 3. UNIVERSAL RATING LOGIC (Electronics + Fashion)
                flat_text = " ".join(card_text)
                rating_match = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐|\([\d,\s]+\)|[\d,\s]+Ratings?)', flat_text, re.IGNORECASE)
                
                if rating_match:
                    deal_info["rating"] = rating_match.group(1)
                else:
                    # Pattern 2: Agar Flipkart ne rating ekdum alag line mein likhi hai (jaise sirf "4.2")
                    for line in card_text:
                        clean_line = line.strip()
                        # Check agar puri line mein sirf 1 se 5 ke beech ka number hai
                        match_single = re.search(r'^([1-4]\.\d|5\.0)\s*(?:★|⭐)?$', clean_line)
                        if match_single:
                            deal_info["rating"] = match_single.group(1)
                            break
                            
                # 🛑 4. THE DOUBLE QUALITY FILTER 
                try:
                    current_rating = float(deal_info["rating"])
                except ValueError:
                    current_rating = 0.0
                    
                try:
                    current_discount = int(deal_info["discount"])
                except ValueError:
                    current_discount = 0

                # Check pass hone par list mein dalega
                if current_rating >= 4.0 and current_discount >= required_discount:
                    deal_info["rating"] = f"{current_rating}★"
                    deal_info["discount"] = f"{current_discount}% Off"
                    
                    print(f"✅ Deal Select Hui: {title[:30]}...")
                    deals.append(deal_info)
                elif current_rating == 0.0 and current_discount >= (required_discount+10) :
                    deal_info["rating"] = "🌟 Bestseller / New Launch"
                    deal_info["discount"] = f"{current_discount}% Off (🔥 MEGA DROP)"
                    print(f"🔥 Loot Deal Select Hui (Hidden Rating): {title[:30]}...")
                    deals.append(deal_info)

                else:
                    print(f"⏩ Skip Kiya: Rating={current_rating}★, Discount={current_discount}%")
                
            except Exception as e:
                print(f"❌ Ek product skip ho gaya: {e}")

        context.close()        
        browser.close()
        print("\n✅ Scraping Complete!")
        return deals