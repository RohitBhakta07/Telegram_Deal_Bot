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
            response = requests.post(url, data=payload)
            # Agar photo successfully chali gayi
            if response.status_code == 200:
                print(f"✅ Telegram par VIP Photo/Message chala gaya! (Channel: {chat_id})")
                return response.json()
            else:
                print(f"⚠️ Photo fail hui: {response.text}")
                print("🔄 Backup: Sirf Text bhej rahe hain...")
        except Exception as e:
            print(f"⚠️ Photo request error: {e}")
    
    # 📝 Backup: Agar photo nahi thi ya photo bhejna fail ho gaya
    url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True  
    }

    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("✅ Telegram par Text Message chala gaya!")
        else:
            print(f"❌ Telegram Error: {response.text}")
        return response.json()
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return None