# telegram/bot.py
import requests
from config import BOT_TOKEN

# ✅ NAYA: Function ab 'chat_id' parameter bhi lega
def send_telegram_message(text, image_url=None, chat_id=None):
    """
    Agar image_url milega, toh badi Photo bhejega (caption ke sath).
    Agar image nahi hogi ya fail ho jaye, toh sirf Text bhejega.
    """
    # Security check: Agar chat_id empty aayi toh ruk jao
    if not chat_id:
        print("❌ Error: Channel ki Chat ID pass nahi ki gayi!")
        return None
    
    # 1. Token ko check karna aur aage-peeche ke spaces hatana
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN khali hai! Dashboard mein jaakar Save karein.")
        return None
        
    clean_token = BOT_TOKEN.strip() # Yeh galti se aaye spaces ko hata dega
    
    # 2. Debugging ke liye Token ka aadha hissa print karna (taaki pata chale token sahi hai ya nahi)
    print(f"🔍 Checking Token... (Start: {clean_token[:10]}...)")

    if image_url and image_url.startswith("http"):
        # 📸 Photo bhejne wala Telegram API
        url = f"https://api.telegram.org/bot{clean_token}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": text,          
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, data=payload, timeout=15)
            # Agar photo successfully chali gayi
            if response.status_code == 200:
                print(f"✅ Telegram par VIP Photo/Message chala gaya! (Channel: {chat_id})")
                return response.json()
            elif response.status_code == 429:
                # 🛡️ HOSTING FIX: Telegram rate limit handle karna
                print(f"⚠️ Telegram Rate Limit! Thoda wait kar rahe hain...")
                try:
                    retry_after = response.json().get('parameters', {}).get('retry_after', 10)
                except:
                    retry_after = 10
                import time
                time.sleep(retry_after)
                # Retry once
                try:
                    response = requests.post(url, data=payload, timeout=15)
                    if response.status_code == 200:
                        print(f"✅ Retry successful! Photo chali gayi.")
                        return response.json()
                except:
                    pass
                print(f"⚠️ Photo retry bhi fail. Text bhej rahe hain...")
            else:
                print(f"⚠️ Photo fail hui: {response.text}")
                print("🔄 Backup: Sirf Text bhej rahe hain...")
        except requests.exceptions.Timeout:
            print("⚠️ Photo request timeout. Text bhej rahe hain...")
        except requests.exceptions.ConnectionError:
            print("⚠️ Internet connection issue. Text bhej rahe hain...")
        except Exception as e:
            print(f"⚠️ Photo request error: {e}")
    
    # 📝 Backup: Agar photo nahi thi ya photo bhejna fail ho gaya
    url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
    
    # 🛡️ HOSTING FIX: Caption 4096 limit, Message 4096 limit
    safe_text = text[:4096] if text else "Deal Check Karo! 🔥"
    
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True  
    }

    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            print("✅ Telegram par Text Message chala gaya!")
        elif response.status_code == 429:
            # 🛡️ Rate limit for text messages too
            print(f"⚠️ Telegram Rate Limit on text!")
            try:
                retry_after = response.json().get('parameters', {}).get('retry_after', 10)
            except:
                retry_after = 10
            import time
            time.sleep(retry_after)
            try:
                response = requests.post(url, data=payload, timeout=15)
                if response.status_code == 200:
                    print("✅ Retry successful!")
            except:
                pass
        else:
            print(f"❌ Telegram Error: {response.text}")
        try:
            return response.json()
        except:
            return None
    except requests.exceptions.Timeout:
        print("❌ Telegram Text Timeout: Server respond nahi kar raha.")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ Telegram Connection Error: Internet down hai ya Telegram blocked hai.")
        return None
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return None