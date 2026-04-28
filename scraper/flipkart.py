# scraper.py
from playwright.sync_api import sync_playwright
import time
import re
import random

def get_flipkart_deals(search_url, required_discount=60):
    deals = []
    browser = None
    context = None
    
    try:
        print("🔍 Opening chrome Browser...")
        with sync_playwright() as p:

            # 🚀 HOSTING UPGRADE: Linux server ke liye special arguments taaki crash na ho
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox", 
                        "--disable-setuid-sandbox", 
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
            except Exception as e:
                print(f"❌ CRITICAL: Browser launch fail hua! Error: {e}")
                print("💡 Possible Fix: 'playwright install chromium' command run karo server par.")
                return deals
            
            # 🛡️ ANTI-BAN UPGRADE: Flipkart ko lagega ki koi asli insaan Windows PC se chala raha hai
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
            ]
            
            try:
                context = browser.new_context(
                    user_agent=random.choice(user_agents),
                    viewport={"width": 1920, "height": 1080},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Upgrade-Insecure-Requests": "1"
                    }
                )
                # 🛑 CRASH FIX: Block images and CSS to save memory & stop crash
                context.route("**/*.{png,jpg,jpeg,webp,svg,gif,css,woff2}", lambda route: route.abort())
                
                page = context.new_page()
            except Exception as e:
                print(f"❌ Browser context/page creation fail: {e}")
                if browser:
                    try:
                        browser.close()
                    except:
                        pass
                return deals
            
            try:
                print("🌐 Flipkart par jaa rahe hain...")
                
                max_retries = 3
                page_loaded = False
                
                for attempt in range(max_retries):
                    try:
                        # Timeout thoda kam rakha hai taaki jaldi retry kar sake
                        page.goto(search_url, timeout=40000, wait_until="domcontentloaded")
                        page_loaded = True
                        break
                    except Exception as e:
                        print(f"⚠️ Page load warning (Attempt {attempt+1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            print("🔄 Retrying in 3 seconds...")
                            time.sleep(3)
                            # 🛡️ HOSTING FIX: Stale page ko replace karo naye page se
                            try:
                                page.close()
                            except:
                                pass
                            try:
                                page = context.new_page()
                            except Exception as page_err:
                                print(f"❌ New page bhi nahi ban rahi: {page_err}")
                                break
                            
                if not page_loaded:
                    print("❌ Failed to load Flipkart page after retries. Connection timed out.")
                    return deals  # finally block cleanup karega
                    
                try:
                    page.wait_for_selector("div[data-id]", timeout=15000)
                except Exception as e:
                    print(f"❌ Failed to find products on page. Flipkart may be blocking or slow: {e}")
                    return deals # finally block cleanup karega
                
                # Page ko thoda neeche scroll karenge taaki saare products load ho jayein
                print("⏬ Page scroll kar rahe hain...")
                try:
                    # 🛑 CRASH FIX: Full bottom scroll memory crash kar sakta hai.
                    # Hum sirf thoda scroll karenge jisse pehle 10 products load ho jayein.
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(2) 
                except Exception as e:
                    print(f"⚠️ Scroll error (ignorable): {e}")
                
                print("📦 Products extract kar rahe hain...\n")
                
                # Flipkart ke products usually 'div[data-id]' tag ke andar hote hain
                try:
                    product_cards = page.locator("div[data-id]").all()
                except Exception as e:
                    print(f"❌ Product cards nahi mil rahe: {e}")
                    return deals  # finally block cleanup karega
                
                # Hum top 5 products nikalenge
                for card in product_cards[:6]:
                    try:
                        # 🛡️ HOSTING FIX: Stale element check
                        try:
                            card_text_full = card.inner_text(timeout=5000).lower()
                        except Exception:
                            print("⚠️ Card text nahi mil raha, skip kar rahe hain...")
                            continue
                            
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
                        href = link_element.get_attribute('href')
                        
                        # 🛡️ HOSTING FIX: Agar href None aaye toh skip karo
                        if not href:
                            print("⚠️ Product ka link nahi mila, skip...")
                            continue
                        
                        if href.startswith("http"):
                            full_link = href
                        else:
                            full_link = f"https://www.flipkart.com{href}"
                        
                        card_text = card.inner_text(timeout=5000).split('\n')
                        
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
                                try:
                                    src = img.get_attribute("src")
                                except:
                                    continue
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
                        try:
                            highlight_elements = card.locator("li").all()
                        except:
                            highlight_elements = []
                        highlights_list = []
                        for el in highlight_elements[:4]:
                            try:
                                text = el.inner_text(timeout=3000).strip()
                                if text:
                                    highlights_list.append(f"🔹 {text}")
                            except:
                                pass
                        
                        if not highlights_list:
                            brand_name = card_text[0] if len(card_text) > 0 else "Top Brand"
                            if brand_name.lower() in ["ad", "sponsored", "bestseller"]:
                                brand_name = card_text[1] if len(card_text) > 1 else "Top Brand"
                            deal_info["highlights"] = f"🔹 Brand: {brand_name}\n🔹 100% Original Product\n🔹 Best Quality & Comfort"
                        else:
                            deal_info["highlights"] = "\n".join(highlights_list)

                        # 🕵️‍♂️ 2. UNIVERSAL PRICE & DISCOUNT LOGIC (Bulletproof Fix)

                        # STEP A: Pehle Discount nikal kar original text se usko 'Mita' (Remove) do
                        try:
                            raw_card_text = card.inner_text(timeout=5000)
                        except:
                            raw_card_text = " ".join(card_text)
                            
                        discount_match = re.search(r'(\d{1,2})\s*%', raw_card_text)
                        if discount_match:
                            deal_info["discount"] = discount_match.group(1)
                            # Text se % wala hissa space se replace kar rahe hain taaki "122333" mix na ho
                            safe_text = re.sub(r'\d{1,2}\s*%', ' ', raw_card_text)
                        else:
                            safe_text = raw_card_text

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

                        # 🌟 3. SUPERCHARGED RATING LOGIC (7 Patterns — Maximum Product Capture)
                        flat_text = " ".join(card_text)
                        extracted_rating = None
                        
                        # Pattern 1: Standard — "4.2★ (1,234 Ratings)" ya "4.2 1234 Ratings"
                        if not extracted_rating:
                            m = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐)?\s*(?:\([\d,\s]+\)|[\d,\s]+Ratings?)', flat_text, re.IGNORECASE)
                            if m: extracted_rating = m.group(1)
                        
                        # Pattern 2: Reviews format — "4.2 Ratings & 234 Reviews" ya "4.2 & 234 Reviews"
                        if not extracted_rating:
                            m = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐)?\s*(?:Ratings?\s*)?(?:&|and)\s*[\d,]+\s*Reviews?', flat_text, re.IGNORECASE)
                            if m: extracted_rating = m.group(1)
                        
                        # Pattern 3: Standalone line — puri line mein sirf "4.2" ya "4.2 ★"
                        if not extracted_rating:
                            for line in card_text:
                                clean_line = line.strip()
                                m = re.search(r'^([1-4]\.\d|5\.0)\s*(?:★|⭐)?$', clean_line)
                                if m:
                                    extracted_rating = m.group(1)
                                    break
                        
                        # Pattern 4: "out of 5" format — "4.2 out of 5"
                        if not extracted_rating:
                            m = re.search(r'([1-4]\.\d|5\.0)\s*out\s*of\s*5', flat_text, re.IGNORECASE)
                            if m: extracted_rating = m.group(1)
                        
                        # Pattern 5: Flipkart short — "4.2★" kahi bhi text mein
                        if not extracted_rating:
                            m = re.search(r'([1-4]\.\d|5\.0)\s*[★⭐]', flat_text)
                            if m: extracted_rating = m.group(1)
                        
                        # Pattern 6: Bare decimal — koi bhi 1.0-5.0 number jo price ya % nahi hai
                        if not extracted_rating:
                            # Prices (₹) aur percentages (%) hata ke search karo
                            clean_for_rating = re.sub(r'₹\s*[\d,]+', '', flat_text)
                            clean_for_rating = re.sub(r'\d+\s*%', '', clean_for_rating)
                            m = re.search(r'(?<!\d)([3-4]\.\d|5\.0)(?!\d)', clean_for_rating)
                            if m: extracted_rating = m.group(1)
                        
                        # Pattern 7: DOM element direct — Flipkart ke rating class se seedha nikalo
                        if not extracted_rating:
                            try:
                                rating_selectors = ["div._3LWZlK", "span._1lRcqv", "div.XQDdHH", "span.Y1HWO0"]
                                for sel in rating_selectors:
                                    try:
                                        el = card.locator(sel).first
                                        rt = el.inner_text(timeout=2000).strip()
                                        m = re.search(r'([1-4]\.\d|5\.0)', rt)
                                        if m:
                                            extracted_rating = m.group(1)
                                            break
                                    except:
                                        continue
                            except:
                                pass
                        
                        # 🔥 Pattern 8: SMART DEEP DIVE — Sirf tab product page par jao jab discount BOHUT ZYADA ho
                        # Agar discount minimum ke aas-paas hai toh time waste mat karo
                        if not extracted_rating and full_link:
                            try:
                                temp_discount = int(deal_info["discount"])
                            except (ValueError, TypeError):
                                temp_discount = 0
                            
                            # 🧠 SMART CHECK: Sirf tab page kholo jab discount minimum se 20%+ zyada ho
                            # Example: Minimum 60% set hai, product 80%+ discount hai → page kholo
                            # Example: Minimum 60% set hai, product 65% discount hai → skip, time waste mat karo
                            if temp_discount >= (required_discount + 20):
                                try:
                                    print(f"  🔎 Rating nahi mili lekin discount {temp_discount}% bohut zyada hai! Product page check kar rahe hain...")
                                    product_page = context.new_page()
                                    try:
                                        product_page.goto(full_link, timeout=25000, wait_until="domcontentloaded")
                                        time.sleep(2)
                                        
                                        # Method A: CSS selectors se rating nikalo
                                        deep_selectors = [
                                            "div._3LWZlK", "span._1lRcqv", "div.XQDdHH", 
                                            "span.Y1HWO0", "div._2d4LTz", "span._1Y-68P",
                                            "div[class*='rating']", "span[class*='rating']"
                                        ]
                                        for sel in deep_selectors:
                                            try:
                                                el = product_page.locator(sel).first
                                                rt = el.inner_text(timeout=2000).strip()
                                                m = re.search(r'([1-4]\.\d|5\.0)', rt)
                                                if m:
                                                    extracted_rating = m.group(1)
                                                    print(f"  ✅ Product page se rating mili: {extracted_rating}★")
                                                    break
                                            except:
                                                continue
                                        
                                        # Method B: Full page text se regex
                                        if not extracted_rating:
                                            try:
                                                page_body = product_page.inner_text("body", timeout=5000)
                                                m = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐|out\s*of\s*5|Ratings?)', page_body, re.IGNORECASE)
                                                if m:
                                                    extracted_rating = m.group(1)
                                                    print(f"  ✅ Product page se rating mili (text): {extracted_rating}★")
                                            except:
                                                pass
                                        
                                        if not extracted_rating:
                                            print(f"  ℹ️ Product par sachmuch rating nahi hai (New/Unrated)")
                                            
                                    except Exception as e:
                                        print(f"  ⚠️ Product page load fail: {e}")
                                    finally:
                                        try:
                                            product_page.close()
                                        except:
                                            pass
                                except Exception as e:
                                    print(f"  ⚠️ Deep rating fetch error: {e}")
                            else:
                                print(f"  ⏩ Rating nahi mili, discount {temp_discount}% minimum ({required_discount}%) ke paas hai. Page visit skip.")
                        
                        if extracted_rating:
                            deal_info["rating"] = extracted_rating
                                    
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
                        elif current_rating == 0.0 and current_discount >= required_discount:
                            deal_info["rating"] = "🌟 Bestseller / New Launch"
                            deal_info["discount"] = f"{current_discount}% Off (🔥 MEGA DROP)"
                            print(f"🔥 Loot Deal Select Hui (Hidden Rating): {title[:30]}...")
                            deals.append(deal_info)

                        else:
                            print(f"⏩ Skip Kiya: Rating={current_rating}★, Discount={current_discount}%")
                        
                    except Exception as e:
                        print(f"❌ Ek product skip ho gaya: {e}")

                print("\n✅ Scraping Complete!")
                
            finally:
                # 🛡️ GUARANTEED CLEANUP: Browser hamesha band hoga, chahe koi bhi error aaye
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    if browser:
                        browser.close()
                except Exception:
                    pass
                    
    except KeyboardInterrupt:
        print("\n⛔ User ne bot manually rok diya (Ctrl+C). Browser safely close ho raha hai...")
    except Exception as e:
        # 🛡️ MASTER SAFETY NET: Agar Playwright ya koi bhi cheez poori tarah crash kare
        print(f"❌ SCRAPER CRITICAL ERROR: {e}")
        print("🔄 Bot continue karega agle round mein...")
    
    return deals


# ==========================================
# 🚀 INSTANT POST SCRAPER: Single Product Page se details nikalega
# ==========================================
def scrape_single_product(product_url):
    """
    Ek single Flipkart product page ko scrape karega aur deal info return karega.
    Yeh Instant Post feature ke liye hai — dashboard se link paste karke turant post karne ke liye.
    """
    deal_info = None
    browser = None
    context = None
    
    try:
        print("🚀 [INSTANT POST] Product page scrape kar rahe hain...")
        with sync_playwright() as p:
            
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox", 
                        "--disable-setuid-sandbox", 
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
            except Exception as e:
                print(f"❌ INSTANT POST: Browser launch fail: {e}")
                return None
            
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ]
            
            try:
                context = browser.new_context(
                    user_agent=random.choice(user_agents),
                    viewport={"width": 1920, "height": 1080},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Upgrade-Insecure-Requests": "1"
                    }
                )
                
                # Instant Post ke liye image chahiye, toh bas media files ko allow karo but CSS/fonts block karo
                context.route("**/*.{css,woff2}", lambda route: route.abort())
                
                page = context.new_page()
            except Exception as e:
                print(f"❌ INSTANT POST: Context creation fail: {e}")
                if browser:
                    try: browser.close()
                    except: pass
                return None
            
            try:
                # Page load karo
                try:
                    page.goto(product_url, timeout=40000, wait_until="domcontentloaded")
                except Exception as e:
                    print(f"❌ INSTANT POST: Page load fail: {e}")
                    return None
                
                time.sleep(3)
                
                # ==========================================
                # 🚀 ROBUST EXTRACTION via HTML/Meta Tags 
                # (CSS classes change, but meta tags & JSON-LD don't)
                # ==========================================
                try:
                    html_content = page.content()
                    page_text = page.inner_text("body", timeout=5000)
                except:
                    html_content = ""
                    page_text = ""
                
                # 1. TITLE
                title = "Flipkart Product"
                m_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content)
                if m_title:
                    title = m_title.group(1).replace("Buy ", "").split(" at ")[0].strip()
                
                # 2. IMAGE
                image_url = ""
                m_img = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content)
                if m_img:
                    image_url = m_img.group(1)
                
                # 3. PRICE
                price = "Check Link"
                # JSON-LD Price
                m_price = re.search(r'"price":\s*(\d+\.?\d*)', html_content)
                if m_price:
                    price_val = int(float(m_price.group(1)))
                    price = f"₹{price_val:,}"
                
                # 4. MRP
                mrp = "Check Link"
                # Search for original price strike-through in text
                prices_found = re.findall(r'₹\s*([\d,]+)', page_text)
                valid_prices = []
                for pr in prices_found:
                    try:
                        val = int(pr.replace(',', ''))
                        if val > 50: valid_prices.append(val)
                    except: pass
                
                if valid_prices:
                    max_price = max(valid_prices)
                    if price != "Check Link":
                        current_price_int = int(price.replace('₹', '').replace(',', ''))
                        if max_price > current_price_int:
                            mrp = f"₹{max_price:,}"
                        else:
                            mrp = price
                    else:
                        mrp = f"₹{max_price:,}"
                
                # 5. RATING
                rating = "🌟 New/Unrated"
                m_rating = re.search(r'"ratingValue":\s*([\d\.]+)', html_content)
                if m_rating:
                    rating = f"{m_rating.group(1)}★"
                else:
                    # Fallback
                    m_rating2 = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐)', page_text)
                    if m_rating2: rating = f"{m_rating2.group(1)}★"
                
                # 6. DISCOUNT
                discount_str = "0% Off"
                m_disc = re.search(r'(\d{1,2})\s*%\s*(?:off|Off|OFF)', page_text)
                if m_disc:
                    discount_str = f"{m_disc.group(1)}% Off"
                elif price != "Check Link" and mrp != "Check Link" and price != mrp:
                    try:
                        p_val = int(price.replace('₹', '').replace(',', ''))
                        m_val = int(mrp.replace('₹', '').replace(',', ''))
                        calc_disc = int(((m_val - p_val) / m_val) * 100)
                        if calc_disc > 0:
                            discount_str = f"{calc_disc}% Off"
                    except: pass
                
                if discount_str == "0% Off":
                    discount_str = "Mega Deal"
                
                # 7. HIGHLIGHTS
                highlights = "🔹 Premium Quality\n🔹 Best in Class\n🔹 Verified Product"
                try:
                    hts = []
                    page_lines = page_text.split('\n')
                    for i, line in enumerate(page_lines):
                        if "Highlights" in line and i+1 < len(page_lines):
                            for j in range(1, 5):
                                if i+j < len(page_lines) and len(page_lines[i+j].strip()) > 3:
                                    hts.append(f"🔹 {page_lines[i+j].strip()}")
                            break
                    if hts: highlights = "\n".join(hts)
                except: pass
                
                deal_info = {
                    "title": title[:80] + ("..." if len(title) > 80 else ""),
                    "link": product_url,
                    "image": image_url,
                    "price": price,
                    "mrp": mrp,
                    "discount": discount_str,
                    "rating": rating,
                    "highlights": highlights
                }
                
                print(f"✅ [INSTANT POST] Product scraped: {title[:40]}...")
                
            finally:
                try:
                    if context: context.close()
                except: pass
                try:
                    if browser: browser.close()
                except: pass
                    
    except Exception as e:
        print(f"❌ INSTANT POST SCRAPER ERROR: {e}")
    
    return deal_info