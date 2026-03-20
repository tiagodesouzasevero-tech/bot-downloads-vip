import telebot
import yt_dlp
import os

# Seu Token já inserido abaixo:
TOKEN = "8629536333:AAGRHgdQYnkSagKtj2wq5jAaBi-bBsCnhBY"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ Acervo Prime Ativo! Mande um link do Instagram, TikTok ou Pinterest que eu baixo para você.")

@bot.message_handler(func=lambda message: True)
def download_video(message):
    url = message.text
    # Verifica se o link é de uma das redes aceitas
    if any(site in url for site in ["instagram.com", "tiktok.com", "pin.it", "pinterest.com"]):
        msg = bot.reply_to(message, "⏳ Processando seu vídeo... aguarde um instante.")
        
        # Nome do arquivo único para evitar erros de permissão
        file_name = f"video_{message.chat.id}.mp4"
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': file_name,
            'quiet': True,
            'no_warnings': True,
        }

        try:
            # Baixa o vídeo usando o yt-dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Envia o arquivo de vídeo para o seu Telegram
            with open(file_name, 'rb') as video:
                bot.send_video(message.chat.id, video)
            
            # Apaga o vídeo do servidor para não ocupar espaço
            os.remove(file_name)
            bot.delete_message(message.chat.id, msg.message_id)
            
        except Exception as e:
            # Se der erro, ele te avisa o que aconteceu
            error_text = str(e)[:100]
            bot.edit_message_text(f"❌ Erro ao baixar: {error_text}", message.chat.id, msg.message_id)
            if os.path.exists(file_name):
                os.remove(file_name)

# Comando para o bot nunca desligar na Railway
if __name__ == "__main__":
    print("O bot do Tiago está rodando...")
    bot.infinity_polling()
