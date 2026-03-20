import telebot
import yt_dlp
import os
import sqlite3
import mercadopago
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURAÇÕES DO TIAGO ---
TOKEN_TELEGRAM = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
TOKEN_MERCADO_PAGO = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
ADMIN_ID = 5410931534 

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(TOKEN_MERCADO_PAGO)

# CAMINHO DO VOLUME (Memória permanente na Railway)
DB_DIR = '/app/data'
DB_PATH = os.path.join(DB_DIR, 'usuarios.db')

def init_db():
    # Cria a pasta do volume se ela não existir
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY, plano TEXT, expira TEXT, downloads_hoje INTEGER, ultima_data TEXT)''')
    conn.commit()
    conn.close()
    print("✅ Banco de dados no Volume inicializado!")

def obter_dados(user_id):
    if user_id == ADMIN_ID:
        return 'Dono VIP', 0, '2099-12-31'
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    hoje = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT plano, expira, downloads_hoje, ultima_data FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users VALUES (?, 'Gratuito', 'Nunca', 0, ?)", (user_id, hoy))
        conn.commit()
        conn.close()
        return 'Gratuito', 0, 'Nunca'
    
    # Reseta contador de downloads se mudou o dia
    if user[3] != hoje:
        cursor.execute("UPDATE users SET downloads_hoje = 0, ultima_data = ? WHERE id = ?", (hoje, user_id))
        conn.commit()
    
    conn.close()
    return user[0], user[2], user[1]

# --- COMANDO DE CAIXA (PAINEL DO TIAGO) ---
@bot.message_handler(commands=['caixa'])
def ver_caixa(message):
    if message.from_user.id == ADMIN_ID:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE plano != 'Gratuito'")
            vips = cursor.fetchone()[0]
            conn.close()
            
            relatorio = (
                f"💰 **PAINEL DE CONTROLE - TIAGO**\n\n"
                f"👥 Usuários totais: {total}\n"
                f"⭐ Assinantes VIP: {vips}\n\n"
                f"Sincronização com Volume: ✅ Ativa"
            )
            bot.reply_to(message, relatorio)
        except Exception as e:
            bot.reply_to(message, f"❌ Erro no banco: {e}")

# --- COMANDO START ---
@bot.message_handler(commands=['start'])
def start(message):
    plano, _, _ = obter_dados(message.from_user.id)
    msg = (
        f"👋 Olá! Bem-vindo ao seu Bot de Downloads.\n\n"
        f"Seu plano atual: **{plano}**\n"
        f"Envie um link do Pinterest ou Instagram para começar!"
    )
    bot.reply_to(message, msg, parse_mode="Markdown")

# --- LÓGICA DE DOWNLOAD ---
@bot.message_handler(func=lambda m: "http" in m.text)
def handle_download(m):
    plano, d_hoje, _ = obter_dados(m.from_user.id)
    
    if plano == 'Gratuito' and d_hoje >= 5:
        bot.reply_to(m, "❌ Você atingiu o limite de 5 downloads diários. Torne-se VIP para baixar ilimitado!")
        return

    msg_espera = bot.reply_to(m, "⏳ Baixando vídeo... (Plano Hobby 🚀)")
    file_name = f"download_{m.from_user.id}.mp4"
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': file_name,
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([m.text])
        
        with open(file_name, 'rb') as video:
            bot.send_video(m.chat.id, video)
        
        # Contabiliza download para usuários gratuitos
        if plano == 'Gratuito':
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET downloads_hoje = downloads_hoje + 1 WHERE id = ?", (m.from_user.id,))
            conn.commit()
            conn.close()
            
        bot.delete_message(m.chat.id, msg_espera.message_id)
        os.remove(file_name)
    except Exception:
        bot.edit_message_text("❌ Erro ao baixar. O link pode ser privado ou inválido.", m.chat.id, msg_espera.message_id)
        if os.path.exists(file_name): os.remove(file_name)

if __name__ == "__main__":
    init_db()
    print("Bot do Tiago rodando no plano Hobby!")
    bot.infinity_polling()
