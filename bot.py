import telebot
import yt_dlp
import os
import sqlite3
from datetime import datetime

# CONFIGURAÇÕES
TOKEN = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
bot = telebot.TeleBot(TOKEN)

# --- FUNÇÕES DE MEMÓRIA (BANCO DE DADOS) ---
def init_db():
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY, plano TEXT, downloads_hoje INTEGER, ultima_data TEXT)''')
    conn.commit()
    conn.close()

def verificar_limite(user_id):
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("SELECT plano, downloads_hoje, ultima_data FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users VALUES (?, 'Gratuito', 0, ?)", (user_id, hoje))
        conn.commit()
        conn.close()
        return True # Liberado (novo usuário)

    plano, downloads, ultima_data = user

    # Reset diário se mudou o dia
    if ultima_data != hoje:
        cursor.execute("UPDATE users SET downloads_hoje = 0, ultima_data = ? WHERE id = ?", (hoje, user_id))
        conn.commit()
        downloads = 0

    conn.close()
    
    if plano != 'Gratuito': return True # VIP não tem limite
    if downloads < 5: return True # Grátis ainda tem saldo
    return False # Bloqueado

def registrar_download(user_id):
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET downloads_hoje = downloads_hoje + 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Bem-vindo ao Bot de Downloads!\nBaixe vídeos do Instagram, Pinterest, TikTok ou Rednote.\n\n💡 Você tem 5 downloads grátis por dia.")

@bot.message_handler(func=lambda message: True)
def download_video(message):
    url = message.text
    user_id = message.from_user.id
    sites = ["instagram.com", "tiktok.com", "pin.it", "pinterest.com", "rednote", "xiaohongshu"]
    
    if any(site in url for site in sites):
        # TESTA O LIMITE ANTES DE TUDO
        if not verificar_limite(user_id):
            bot.reply_to(message, "🚫 Você atingiu seu limite de 5 downloads hoje!\nPara baixar sem limites, assine o Premium.")
            return

        msg = bot.reply_to(message, "⚡ Baixando seu vídeo, aguarde um instante...")
        file_name = f"video_{user_id}.mp4"
        
        # SUA CONFIGURAÇÃO QUE JÁ FUNCIONA (NÃO MEXI)
        ydl_opts = {
            'format': 'best',
            'outtmpl': file_name,
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.google.com/',
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            if os.path.exists(file_name):
                with open(file_name, 'rb') as video:
                    bot.send_video(message.chat.id, video)
                os.remove(file_name)
                registrar_download(user_id) # SOMA +1 NO CONTADOR
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Erro ao baixar conteúdo.", message.chat.id, msg.message_id)
        except Exception:
            bot.edit_message_text("❌ Link indisponível.", message.chat.id, msg.message_id)
            if os.path.exists(file_name): os.remove(file_name)

if __name__ == "__main__":
    init_db() # INICIA O BANCO
    bot.infinity_polling()
