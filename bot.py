import telebot
import yt_dlp
import os

# Seu Token já inserido abaixo:
TOKEN = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ Acervo Prime Ativo! Mande links do Instagram, TikTok ou Pinterest.")

@bot.message_handler(func=lambda message: True)
def download_video(message):
    url = message.text
    # Lista de sites aceitos, incluindo Pinterest
    if any(site in url for site in ["instagram.com", "tiktok.com", "pin.it", "pinterest.com"]):
        msg = bot.reply_to(message, "⏳ Processando... Isso pode levar 20 segundos no Pinterest.")
        
        file_name = f"video_{message.chat.id}.mp4"
        
        # Configurações especiais para o Pinterest não bloquear
        ydl_opts = {
            'format': 'best',
            'outtmpl': file_name,
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
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
                bot.edit_message_text("❌ Não consegui gerar o arquivo de vídeo. Tente outro link.", message.chat.id, msg.message_id)
            
        except Exception as e:
            # Mostra o erro exato para sabermos se o Pinterest bloqueou
            error_text = str(e)[:100]
            bot.edit_message_text(f"❌ Erro no download: {error_text}", message.chat.id, msg.message_id)
            if os.path.exists(file_name):
                os.remove(file_name)

if __name__ == "__main__":
    print("Bot do Tiago rodando com Pinterest fix...")
    bot.infinity_polling()
