import telebot
import yt_dlp
import os
import sqlite3
import mercadopago
import random
import time
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
# Seu Token de produção revisado:
TOKEN_MERCADO_PAGO = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(TOKEN_MERCADO_PAGO)

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
    cursor.execute("SELECT plano, expira, downloads_hoje, ultima_data FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users VALUES (?, 'Gratuito', 'Nunca', 0, ?)", (user_id, hoje))
        conn.commit()
        conn.close()
        return 'Gratuito', 0, 'Nunca'
    if user[3] != hoje:
        cursor.execute("UPDATE users SET downloads_hoje = 0, ultima_data = ? WHERE id = ?", (hoje, user_id))
        conn.commit()
        conn.close()
        return user[0], 0, user[1]
    conn.close()
    return user[0], user[2], user[1]

# --- MENU DE PLANOS ---
@bot.message_handler(commands=['planos', 'start'])
def menu_principal(message):
    plano, downloads, _ = obter_dados(message.from_user.id)
    restantes = 5 - downloads if plano == 'Gratuito' else "Ilimitado"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10"))
    markup.add(InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69"))
    markup.add(InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="buy_1900"))
    
    texto = (f"👋 **Bot de Downloads VIP**\n\n📊 Plano: **{plano}**\n💡 Saldo: **{restantes}** downloads gratuitos hoje.\n\n"
             "Escolha um plano para liberar acesso ilimitado:")
    bot.send_message(message.chat.id, texto, reply_markup=markup, parse_mode="Markdown")

# --- PROCESSAMENTO DO PIX ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def gerar_pix(call):
    # CORREÇÃO: Isso aqui remove o carregamento infinito do botão imediatamente
    bot.answer_callback_query(call.id, "Gerando código PIX...")
    
    precos = {"buy_10": 10.0, "buy_69": 69.9, "buy_1900": 1900.0}
    valor = precos[call.data]
    
    payment_data = {
        "transaction_amount": valor,
        "description": f"Plano VIP Usuário {call.from_user.id}",
        "payment_method_id": "pix",
        "payer": {"email": "cliente@pagamento.com"}
    }
    
    try:
        resultado = sdk.payment().create(payment_data)
        pagamento = resultado["response"]
        
        # Pega o código copia e cola
        pix_copia_e_cola = pagamento['point_of_interaction']['transaction_data']['qr_code']
        
        msg = (f"✅ **PIX Gerado com Sucesso!**\n\n"
               f"💰 Valor: R${valor:.2f}\n\n"
               f"Copia e cola abaixo:\n\n`{pix_copia_e_cola}`\n\n"
               f"💡 O acesso é liberado assim que o pagamento for confirmado.")
        
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar PIX. Verifique se o Token está ativo no Mercado Pago.")

# --- MOTOR DE DOWNLOAD ---
@bot.message_handler(func=lambda message: True)
def handle_download(message):
    plano, downloads, _ = obter_dados(message.from_user.id)
    url = message.text
    
    if "http" in url:
        if plano == 'Gratuito' and downloads >= 5:
            bot.reply_to(message, "🚫 Limite diário atingido! Digite /planos para assinar.")
            return

        wait = bot.reply_to(message, "⚡ Processando... aguarde.")
        file_name = f"dl_{message.from_user.id}.mp4"
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': file_name,
            'quiet': True,
            'user_agent': random.choice(USER_AGENTS),
            'referer': 'https://www.google.com/'
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            with open(file_name, 'rb') as vid:
                bot.send_video(message.chat.id, vid)
            
            if plano == 'Gratuito':
                conn = sqlite3.connect('usuarios.db')
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET downloads_hoje = downloads_hoje + 1 WHERE id = ?", (message.from_user.id,))
                conn.commit()
                conn.close()
            
            os.remove(file_name)
            bot.delete_message(message.chat.id, wait.message_id)
        except:
            bot.edit_message_text("❌ Erro ao baixar vídeo. Verifique o link.", message.chat.id, wait.message_id)
            if os.path.exists(file_name): os.remove(file_name)

if __name__ == "__main__":
    init_db()
    bot.infinity_polling()
