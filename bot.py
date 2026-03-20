import telebot
import yt_dlp
import os

# Seu Token
TOKEN = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ Bot Ativo! Envie o link do Instagram, Pinterest, TikTok ou Rednote para baixar.")

@bot.message_handler(func=lambda message: True)
def download_video(message):
    url = message.text
    sites_aceitos = ["instagram.com", "tiktok.com", "pin.it", "pinterest.com", "xiaohongshu.com", "rednote"]
    
    if any(site in url for site in sites_aceitos):
        msg = bot.reply_to(message, "⚡ Baixando seu vídeo, aguarde um instante...")
        
        file_name = f"video_{message.chat.id}.mp4"
        
        # CONFIGURAÇÃO REFORÇADA ANTI-BLOQUEIO
        ydl_opts = {
            'format': 'best', # Mudamos para 'best' para ser mais compatível
            'outtmpl': file_name,
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.google.com/', # Engana o site achando que você veio do Google
            'noplaylist': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            if os.path.exists(file_name):
                with open(file_name, 'rb') as video:
                    bot.send_video(message.chat.id, video)
                
                os.remove(file_name)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Ocorreu um erro ao gerar o vídeo. Tente novamente.", message.chat.id, msg.message_id)
            
        except Exception as e:
            # Se der erro, ele tenta uma segunda vez com outra configuração mais simples
            try:
                ydl_opts_simples = {'format': 'mp4', 'outtmpl': file_name}
                with yt_dlp.YoutubeDL(ydl_opts_simples) as ydl:
                    ydl.download([url])
                with open(file_name, 'rb') as video:
                    bot.send_video(message.chat.id, video)
                os.remove(file_name)
                bot.delete_message(message.chat.id, msg.message_id)
            except:
                bot.edit_message_text("❌ Link temporariamente indisponível. Tente outro vídeo.", message.chat.id, msg.message_id)
                if os.path.exists(file_name):
                    os.remove(file_name)

if __name__ == "__main__":
    bot.infinity_polling()
