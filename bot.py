import telebot
import requests
import sqlite3
from datetime import datetime

# --- CONFIGURAÇÕES DO TIAGO ---
API_TOKEN = '8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY'
MP_ACCESS_TOKEN = 'APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659'

bot = telebot.TeleBot(API_TOKEN)

# --- BANCO DE DADOS (CONTROLE DE DOWNLOADS) ---
def init_db():
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY, downloads INTEGER, dia TEXT, vip INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def checar_limite(user_id):
    hoje = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('usuarios.db')
    cursor = conn.cursor()
    cursor.execute("SELECT downloads, dia, vip FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute("INSERT INTO users (id, downloads, dia) VALUES (?, ?, ?)", (user_id, 1, hoje))
        conn.commit()
        return True, 1
    
    downloads, dia, vip = row
    if vip == 1: return True, 999 

    if dia != hoje:
        cursor.execute("UPDATE users SET downloads = 1, dia = ? WHERE id = ?", (hoje, user_id))
        conn.commit()
        return True, 1
    
    if downloads < 5:
        cursor.execute("UPDATE users SET downloads = downloads + 1 WHERE id = ?", (user_id,))
        conn.commit()
        return True, downloads + 1
    
    return False, downloads

def gerar_pix(user_id):
    url = "https://api.mercadopago.com/v1/payments"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    payload = {
        "transaction_amount": 10.00,
        "description": "Acesso VIP Bot de Downloads",
        "payment_method_id": "pix",
        "payer": {"email": f"user_{user_id}@bot.com"}
    }
    res = requests.post(url, json=payload, headers=headers).json()
    return res['point_of_interaction']['transaction_data']['qr_code']

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 **Bem-vindo ao Bot de Downloads!**\n\n✅ Baixo vídeos do Reels, TikTok, Pinterest e Shopee.\n🎁 Você tem **5 downloads grátis** por dia!")

@bot.message_handler(func=lambda m: True)
def processar_link(message):
    url = message.text.lower()
    user_id = message.from_user.id

    if "youtube.com" in url or "youtu.be" in url:
        bot.reply_to(message, "❌ **Opa!** Não baixamos do YouTube por segurança.\nTente Reels, TikTok ou Pinterest!")
        return

    pode_baixar, contagem = checar_limite(user_id)

    if pode_baixar:
        bot.reply_to(message, f"⏳ **Processando seu vídeo...**\n(Download {contagem}/5 do dia)")
        # A lógica de download entra aqui no próximo passo
    else:
        pix_copia_cola = gerar_pix(user_id)
        msg_pix = f"🚀 **Limite Diário Atingido!**\n\nPara continuar baixando sem limites hoje e sempre, torne-se **VIP por apenas R$ 10,00**.\n\n🔑 **PIX Copia e Cola:**\n`{pix_copia_cola}`\n\n*Após pagar, o acesso é liberado na hora!*"
        bot.send_message(message.chat.id, msg_pix, parse_mode="Markdown")

init_db()
print("Bot do Tiago ligado!")
bot.polling()