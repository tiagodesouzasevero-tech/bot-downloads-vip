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

# Lista de Agentes para evitar bloqueios das redes sociais
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1'
]

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY, plano TEXT, expira TEXT, downloads_hoje INTEGER, ultima_data TEXT)''')
    conn.commit()
    conn.close()

def obter_dados(user_id):
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    # Identifica você pelo nome de usuário ou ID para ser VIP Vitalício
    # Se o ID falhar, o bot verifica se é você
    cursor.execute("SELECT plano, expira, downloads_hoje, ultima_data FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        # Criando novo usuário com 5 downloads gratuitos
        cursor.execute("INSERT INTO users VALUES (?, 'Gratuito', 'Nunca', 0, ?)", (user_id, hoje))
        conn.commit()
        user = ('Gratuito', 'Nunca', 0, hoje)
    
    # Se mudar o dia, reseta os 5 downloads gratuitos
    if user[3] != hoje:
        cursor.execute("UPDATE users SET downloads_hoje = 0, ultima_data = ? WHERE id = ?", (hoje, user_id))
        conn.commit()
        return user[0], 0, user[1]
        
    conn.close()
    return user[0], user[2], user[1]

# --- COMANDO PARA VOCÊ SE TORNAR VIP ---
@bot.message_handler(commands=['ativar_tiago'])
def ativar_admin(message):
    conn = sqlite3.connect('usuarios.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET plano = 'Mensal', expira = '2099-12-31' WHERE id = ?", (message.from_user.id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, "✅ Tiago, seu acesso VIP Vitalício foi ativado com sucesso!")

# --- MENUS ---
@bot.message_handler(commands=['start', 'planos'])
def menu_principal(message):
    plano, downloads, expira = obter_dados(message.from_user.id)
    restantes = 5 - downloads if plano == 'Gratuito' else "Ilimitado"
    
    markup = InlineKeyboardMarkup()
    if plano == 'Gratuito':
        markup.add(InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10"))
        markup.add(InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69"))
        markup.add(InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="buy_1900"))
    
    texto = (f"👋 **Bot de Downloads VIP**\n\n📊 Plano: **{plano}**\n"
             f"📅 Validade: **{expira}**\n"
             f"💡 Saldo: **{restantes}** hoje.")
    bot.send_message(message.chat.id, texto, reply_markup=markup, parse_mode="Markdown")

# --- PAGAMENTOS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def gerar_pagamento(call):
    bot.answer_callback_query(call.id, "Gerando PIX...")
    precos = {"buy_10": 10.0, "buy_69": 69.9, "buy_1900": 1900.0}
    plano_nome = {"buy_10": "Mensal", "buy_69": "Anual", "buy_1900": "Vitalício"}[call.data]
    valor = precos[call.data]
    
    payment_data = {
        "transaction_amount": valor,
        "description": f"Plano {plano_nome}",
        "payment_method_id": "pix",
        "payer": {"email": "contato@tiago.com"}
    }
    
    try:
        pagamento = sdk.payment().create(payment_data)
        pix_code = pagamento["response"]['point_of_interaction']['transaction_data']['qr_code']
        pay_id = pagamento["response"]['id']
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f"check_{pay_id}_{plano_nome}"))
        
        bot.send_message(call.message.chat.id, f"⚠️ **PIX de R${valor:.2f} Gerado!**\n\nCopia e cola:\n`{pix_code}`", reply_markup=markup, parse_mode="Markdown")
    except:
        bot.send_message(call.message.chat.id, "❌ Erro ao conectar com Mercado Pago.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_"))
def validar_pix(call):
    _, pay_id, plano_nome = call.data.split("_")
    res = sdk.payment().get(pay_id)
    if res["response"]["status"] == "approved":
        dias = {"Mensal": 30, "Anual": 365, "Vitalício": 99999}[plano_nome]
        expira = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
        
        conn = sqlite3.connect('usuarios.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET plano = ?, expira = ? WHERE id = ?", (plano_nome, expira, call.from_user.id))
        conn.commit()
        conn.close()
        bot.edit_message_text(f"✅ **Plano {plano_nome} ativado!**", call.message.chat.id, call.message.id)
    else:
        bot.answer_callback_query(call.id, "❌ Pagamento não aprovado.", show_alert=True)

# --- DOWNLOADS ---
@bot.message_handler(func=lambda message: True)
def baixar(message):
    plano, downloads, _ = obter_dados(message.from_user.id)
    url = message.text
    
    if "http" in url:
        if plano == 'Gratuito' and downloads >= 5:
            bot.reply_to(message, "🚫 Limite diário atingido! Use /planos.")
            return

        msg_wait = bot.reply_to(message, "⏳ Baixando vídeo...")
        file_name = f"dl_{message.from_user.id}.mp4"
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': file_name,
            'quiet': True,
            'user_agent': random.choice(USER_AGENTS)
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            with open(file_name, 'rb') as video:
                bot.send_video(message.chat.id, video)
            
            if plano == 'Gratuito':
                conn = sqlite3.connect('usuarios.db')
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET downloads_hoje = downloads_hoje + 1 WHERE id = ?", (message.from_user.id,))
                conn.commit()
                conn.close()
            
            os.remove(file_name)
            bot.delete_message(message.chat.id, msg_wait.message_id)
        except:
            bot.edit_message_text("❌ Erro ao baixar vídeo. Verifique o link.", message.chat.id, msg_wait.message_id)
            if os.path.exists(file_name): os.remove(file_name)

if __name__ == "__main__":
    init_db()
    bot.infinity_polling()
