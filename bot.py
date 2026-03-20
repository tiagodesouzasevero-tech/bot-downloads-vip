import telebot
import yt_dlp
import os
import sqlite3
import mercadopago
import random
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
TOKEN_MERCADO_PAGO = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(TOKEN_MERCADO_PAGO)

# Lista de identidades para evitar bloqueios
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
]

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('usuarios.db', check_same_thread=False, timeout=20)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY, plano TEXT, expira TEXT, downloads_hoje INTEGER, ultima_data TEXT)''')
    conn.commit()
    conn.close()

def obter_dados(user_id):
    conn = sqlite3.connect('usuarios.db', check_same_thread=False, timeout=20)
    cursor = conn.cursor()
    hoje = datetime.now()
    data_hoje = hoje.strftime("%Y-%m-%d")
    cursor.execute("SELECT plano, expira, downloads_hoje, ultima_data FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users VALUES (?, 'Gratuito', 'Nunca', 0, ?)", (user_id, data_hoje))
        conn.commit()
        conn.close()
        return 'Gratuito', 0, 'Nunca'
    
    if user[3] != data_hoje:
        cursor.execute("UPDATE users SET downloads_hoje = 0, ultima_data = ? WHERE id = ?", (data_hoje, user_id))
        conn.commit()
        conn.close()
        return user[0], 0, user[1]
        
    conn.close()
    return user[0], user[2], user[1]

# --- MENSAGENS E PAGAMENTO ---
@bot.message_handler(commands=['start', 'planos'])
def menu_principal(message):
    plano, downloads, _ = obter_dados(message.from_user.id)
    restantes = 5 - downloads if plano == 'Gratuito' else "Ilimitado"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10"))
    markup.add(InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69"))
    markup.add(InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="buy_1900"))
    
    texto = (f"👋 **Bem-vindo ao Bot de Downloads!**\n\n"
             f"📊 Seu plano: **{plano}**\n"
             f"💡 Saldo: **{restantes}** downloads gratuitos hoje.\n\n"
             f"🔥 Assine para baixar sem limites:")
    bot.send_message(message.chat.id, texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def gerar_pagamento(call):
    valor = {"buy_10": 10.00, "buy_69": 69.90, "buy_1900": 1900.00}[call.data]
    plano_nome = {"buy_10": "Mensal", "buy_69": "Anual", "buy_1900": "Vitalício"}[call.data]
    
    bot.answer_callback_query(call.id, "Gerando PIX...")
    payment_data = {
        "transaction_amount": valor,
        "description": f"Plano {plano_nome} - Usuário {call.from_user.id}",
        "payment_method_id": "pix",
        "payer": {"email": "contato@tiago.com"}
    }
    pagamento = sdk.payment().create(payment_data)
    info = pagamento["response"]
    copia_e_cola = info['point_of_interaction']['transaction_data']['qr_code']
    pay_id = info['id']
    
    msg = (f"⚠️ **PIX Gerado!**\n\nCopia e cola:\n`{copia_e_cola}`\n\n"
           f"O sistema libera o acesso **automaticamente** após o pagamento.")
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Já paguei! Verificar", callback_data=f"check_{pay_id}_{plano_nome}"))
    bot.send_message(call.message.chat.id, msg, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_"))
def validar_pix(call):
    _, pay_id, plano_nome = call.data.split("_")
    res = sdk.payment().get(pay_id)
    if res["response"]["status"] == "approved":
        dias = {"Mensal": 30, "Anual": 365, "Vitalício": 99999}[plano_nome]
        expira = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
        
        conn = sqlite3.connect('usuarios.db', check_same_thread=False, timeout=20)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET plano = ?, expira = ? WHERE id = ?", (plano_nome, expira, call.from_user.id))
        conn.commit()
        conn.close()
        bot.edit_message_text(f"✅ **PAGAMENTO CONFIRMADO!**\nPlano {plano_nome} liberado!", call.message.chat.id, call.message.id)
    else:
        bot.answer_callback_query(call.id, "❌ Pagamento não detectado. Tente novamente em instantes.", show_alert=True)

# --- DOWNLOAD BLINDADO ---
@bot.message_handler(func=lambda message: True)
def baixar(message):
    plano, downloads, _ = obter_dados(message.from_user.id)
    url = message.text
    sites = ["instagram.com", "tiktok.com", "pin.it", "pinterest.com", "rednote", "xiaohongshu"]

    if any(site in url for site in sites):
        if plano == 'Gratuito' and downloads >= 5:
            bot.reply_to(message, "🚫 Limite diário atingido! Use /planos para assinar.")
            return

        msg_wait = bot.reply_to(message, "⚡ Baixando vídeo, aguarde...")
        file_name = f"video_{message.from_user.id}_{random.randint(1,1000)}.mp4"
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': file_name,
            'quiet': True,
            'user_agent': random.choice(USER_AGENTS),
            'referer': 'https://www.google.com/',
            'nocheckcertificate': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            with open(file_name, 'rb') as video:
                bot.send_video(message.chat.id, video)
            
            if plano == 'Gratuito':
                conn = sqlite3.connect('usuarios.db', check_same_thread=False, timeout=20)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET downloads_hoje = downloads_hoje + 1 WHERE id = ?", (message.from_user.id,))
                conn.commit()
                conn.close()
                bot.send_message(message.chat.id, f"✅ Vídeo entregue! Restam **{4 - downloads}** downloads gratuitos hoje.")
            
            os.remove(file_name)
            bot.delete_message(message.chat.id, msg_wait.message_id)
        except:
            bot.edit_message_text("❌ Erro ao baixar. O link pode ser privado ou instável no momento.", message.chat.id, msg_wait.message_id)
            if os.path.exists(file_name): os.remove(file_name)

if __name__ == "__main__":
    init_db()
    bot.infinity_polling()
