import os
import telebot

# Configurações do Bot
# SEU NOVO TOKEN GERADO NO BOTFATHER
TOKEN_TELEGRAM = "8629536333:AAEV4IcvFt5CTRqQVz5yYXmNOXvcgaZygGE"

# Caminho do volume na Railway (onde os arquivos ficam salvos)
# Se você seguiu o padrão, o ponto de montagem é /data
VOLUME_PATH = "/data"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# Garantir que a pasta do volume existe
if not os.path.exists(VOLUME_PATH):
    os.makedirs(VOLUME_PATH)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ Bot de Downloads Online!\n\nUse /caixa para ver o que tem no seu volume.")

@bot.message_handler(commands=['caixa'])
def list_files(message):
    try:
        files = os.listdir(VOLUME_PATH)
        if not files:
            bot.reply_to(message, "📦 O volume está vazio.")
        else:
            lista = "\n".join(files)
            bot.reply_to(message, f"📂 Arquivos no volume:\n\n{lista}")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao acessar volume: {e}")

# Iniciar o bot
print("Bot iniciado com sucesso...")
bot.infinity_polling()
