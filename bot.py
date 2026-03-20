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
    
    # Lista de sites aceitos (incluindo Rednote)
    sites_aceitos = ["instagram.com", "tiktok.com", "pin.it", "pinterest.com", "xiaohongshu.com", "rednote"]
    
    if any(site in url for site in sites_aceitos):
        # MENSAGEM COM EMOJI DE MOVIMENTO (RAIO)
        msg = bot.reply_to(message, "⚡ Baixando seu vídeo, aguarde um instante...")
        
        file_name = f"video_{message.chat.id}.mp4"
        
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': file_name,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0',
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
                bot.edit_message_text("❌ Não foi possível baixar este conteúdo.", message.chat.id, msg.message_id)
            
        except Exception:
            bot.edit_message_text("❌ Erro ao processar o vídeo. Verifique se o link é público.", message.chat.id, msg.message_id)
            if os.path.exists(file_name):
                os.remove(file_name)

if __name__ == "__main__":
    bot.infinity_polling()
