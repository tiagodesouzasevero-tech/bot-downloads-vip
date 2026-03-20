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

def obter_dados_utilizador(user_id):
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("SELECT plano, downloads_hoje, ultima_data FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users VALUES (?, 'Gratuito', 0, ?)", (user_id, hoje))
        conn.commit()
        user = ('Gratuito', 0, hoje)
    elif user[2] != hoje:
        cursor.execute("UPDATE users SET downloads_hoje = 0, ultima_data = ? WHERE id = ?", (hoje, user_id))
        conn.commit()
        user = (user[0], 0, hoje)
    
    conn.close()
    return user

def registrar_download(user_id):
    conn = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET downloads_hoje = downloads_hoje + 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    plano, downloads, _ = obter_dados_utilizador(message.from_user.id)
    restantes = 5 - downloads if plano == 'Gratuito' else "Ilimitado"
    bot.reply_to(message, f"👋 **Bem-vindo ao Bot de Downloads!**\n\n📥 Envie links do Instagram, Pinterest, TikTok ou Rednote.\n\n💡 Seu saldo: **{restantes}** downloads grátis hoje.")

@bot.message_handler(func=lambda message: True)
def download_video(message):
    url = message.text
    user_id = message.from_user.id
    plano, downloads, _ = obter_dados_utilizador(user_id)
    
    sites = ["instagram.com", "tiktok.com", "pin.it", "pinterest.com", "rednote", "xiaohongshu"]
    
    if any(site in url for site in sites):
        # TESTA O LIMITE
        if plano == 'Gratuito' and downloads >= 5:
            bot.reply_to(message, "🚫 **Limite atingido!**\nVocê já usou os seus 5 downloads de hoje.\n\n🔥 Assine o Premium para ter acesso ilimitado!")
            return

        msg = bot.reply_to(message, "⚡ Baixando seu vídeo, aguarde um instante...")
        file_name = f"video_{user_id}.mp4"
        
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
                registrar_download(user_id)
                bot.delete_message(message.chat.id, msg.message_id)
                
                # MENSAGEM DE CONTAGEM APÓS O DOWNLOAD
                novos_dados = obter_dados_utilizador(user_id)
                restantes = 5 - novos_dados[1]
                if plano == 'Gratuito':
                    bot.send_message(message.chat.id, f"✅ Vídeo entregue! Restam **{restantes}** downloads gratuitos hoje.")
            
            else:
                bot.edit_message_text("❌ Erro ao processar link.", message.chat.id, msg.message_id)
        except Exception:
            bot.edit_message_text("❌ Link indisponível ou privado.", message.chat.id, msg.message_id)
            if os.path.exists(file_name): os.remove(file_name)

if __name__ == "__main__":
    init_db()
    bot.infinity_polling()
