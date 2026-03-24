import os, telebot, yt_dlp, json
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"
CHAVE_PIX_INFINITE = "dc359b2c-d52f-48b5-b022-3c4fb3a8ddb5"
LINK_SUPORTE = "https://t.me/suporteafiliadoclippro"
ADMIN_ID = 493336271

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# --- FUNÇÕES DE USUÁRIO ---
def obter_usuario(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    hoje = datetime.now().strftime('%Y-%m-%d')
    if not user:
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": hoje}
        usuarios_col.insert_one(user)
    elif user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": uid}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    v_ate = user.get("vip_ate")
    if v_ate == "Vitalício": return True
    if not v_ate: return False
    try:
        return datetime.now() < datetime.strptime(v_ate, '%Y-%m-%d')
    except: return False

# --- COMANDOS ADMIN ---
@bot.message_handler(commands=['darvip'])
def dar_vip_manual(message):
    if message.from_user.id == ADMIN_ID:
        try:
            args = message.text.split()
            alvo_id, dias = args[1], int(args[2])
            nova_data = "Vitalício" if dias >= 3650 else (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
            usuarios_col.update_one({"_id": str(alvo_id)}, {"$set": {"vip_ate": nova_data}})
            bot.reply_to(message, f"✅ VIP liberado para {alvo_id}!")
            bot.send_message(alvo_id, "🎉 **PAGAMENTO CONFIRMADO!**\nSeu acesso VIP foi liberado.")
        except: bot.reply_to(message, "❌ Use: `/darvip ID DIAS`")

@bot.message_handler(commands=['zerar'])
def zerar_contador(message):
    if message.from_user.id == ADMIN_ID:
        try:
            args = message.text.split()
            alvo_id = args[1]
            usuarios_col.update_one({"_id": str(alvo_id)}, {"$set": {"downloads_hoje": 0}})
            bot.reply_to(message, f"✅ Contador do usuário {alvo_id} foi zerado!")
            bot.send_message(alvo_id, "🔄 Suas tentativas diárias foram resetadas pelo suporte. Pode voltar a baixar!")
        except: bot.reply_to(message, "❌ Use: `/zerar ID`")

@bot.message_handler(commands=['avisogeral'])
def aviso_geral(message):
    if message.from_user.id == ADMIN_ID:
        msg_texto = message.text.replace('/avisogeral', '').strip()
        if not msg_texto:
            return bot.reply_to(message, "❌ Digite a mensagem após o comando.")
        usuarios = usuarios_col.find({}, {"_id": 1})
        cont = 0
        for u in usuarios:
            try:
                bot.send_message(u["_id"], msg_texto, parse_mode="Markdown")
                cont += 1
            except: pass
        bot.reply_to(message, f"📢 Aviso enviado para {cont} usuários!")

@bot.message_handler(func=lambda m: m.text == "⚙️ Painel Admin")
def painel_admin(message):
    if message.from_user.id == ADMIN_ID:
        total_users = usuarios_col.count_documents({})
        hoje_str = datetime.now().strftime('%Y-%m-%d')
        vips_ativos = usuarios_col.count_documents({"$or": [{"vip_ate": "Vitalício"}, {"vip_ate": {"$gte": hoje_str}}]})
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$downloads_hoje"}}}]
        res_downloads = list(usuarios_col.aggregate(pipeline))
        downloads_totais_hoje = res_downloads[0]['total'] if res_downloads else 0

        texto_admin = (
            "🛠 **PAINEL DE CONTROLE ADMIN**\n\n"
            f"👤 Usuários Totais: `{total_users}`\n"
            f"💎 VIPs Ativos: `{vips_ativos}`\n"
            f"📥 Downloads Hoje: `{downloads_totais_hoje}`\n\n"
            "🚀 **COMANDOS DISPONÍVEIS:**\n"
            "• `/darvip [ID] [Dias]`\n"
            "• `/zerar [ID]`\n"
            "• `/avisogeral [Mensagem]`"
        )
        bot.send_message(message.chat.id, texto_admin, parse_mode="Markdown")

# --- INTERFACE ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    texto = (f"🚀 **AfiliadoClip Pro**\n\nBaixe vídeos em HD do TikTok, Pinterest e RedNote.\n\n"
             f"• Duração máx: 90s\n• Sua ID: `{message.from_user.id}`\n\n{status}")
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    if message.from_user.id == ADMIN_ID:
        markup.row("⚙️ Painel Admin")
    bot.send_message(message.chat.id, texto, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 Planos VIP")
def mostrar_planos(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
    )
    bot.send_message(message.chat.id, "Escolha seu plano:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛠 Suporte")
def suporte(message):
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Chamar no Suporte", url=LINK_SUPORTE))
    bot.send_message(message.chat.id, "👋 Precisa de ajuda? Clique abaixo:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def pag_manual(call):
    valor = call.data.split("_")[1]
    msg = (f"💎 **Plano: R$ {valor}**\n\nPix Copia e Cola:\n`{CHAVE_PIX_INFINITE}`\n\n"
           f"⚠️ Envie o comprovante e sua ID: `{call.from_user.id}`")
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📤 Enviar Comprovante", url=LINK_SUPORTE))
    bot.send_message(call.message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

# --- DOWNLOADER ---
@bot.message_handler(func=lambda message: message.text and "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip_status = is_vip(message.from_user.id)
    
    # Bloqueia se já tiver passado de 5
    if not vip_status and user.get("downloads_hoje", 0) >= 5:
        bot.reply_to(message, "⚠️ **Limite diário atingido (5/5)!**\nPara continuar baixando sem limites, adquira um de nossos planos VIP abaixo: 👇")
        return mostrar_planos(message)

    status_msg = bot.reply_to(message, "✅ Seu link já entrou na fila de download! Aguarde só alguns instantes enquanto processamos 👊")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'nocheckcertificate': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('duration', 0) > 90:
                return bot.edit_message_text("⚠️ Vídeo muito longo (máx 90s).", message.chat.id, status_msg.message_id)

        url_lower = url.lower()
        is_pinterest = ("pin.it" in url_lower) or ("pinterest" in url_lower)
        is_tiktok = ("tiktok.com" in url_lower) or ("vm.tiktok.com" in url_lower) or ("vt.tiktok.com" in url_lower)
        is_rednote = ("xiaohongshu.com" in url_lower) or ("xhslink.com" in url_lower) or ("rednote" in url_lower)

        common_opts = {
            'outtmpl': file_name,
            'nocheckcertificate': True,
            'quiet': True,
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'retries': 3,
            'fragment_retries': 3,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0',
                'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'
            }
        }

        if is_pinterest:
            formatos = [
                'best[width<=720][height<=1280][fps<=30]',
                'best[width<=720][height<=1280]',
                'best[width<=720]'
            ]
        elif is_tiktok:
            formatos = [
                'bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[width<=720][height<=1280][fps<=30]',
                'bestvideo[height<=1280][fps<=30]+bestaudio/best[height<=1280][fps<=30]',
                'best[width<=720][height<=1280][fps<=30]',
                'best[width<=720][height<=1280]',
                'best[width<=720]'
            ]
        elif is_rednote:
            formatos = [
                'bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[width<=720][height<=1280][fps<=30]',
                'best[width<=720][height<=1280][fps<=30]',
                'best[width<=720][height<=1280]',
                'best[width<=720]'
            ]
        else:
            formatos = [
                'bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[width<=720][height<=1280][fps<=30]',
                'best[width<=720][height<=1280][fps<=30]',
                'best[width<=720][height<=1280]',
                'best[width<=720]'
            ]

        baixou = False
        ultimo_erro = None

        for fmt in formatos:
            try:
                opts = common_opts.copy()
                opts['format'] = fmt

                if is_pinterest:
                    opts['http_headers'] = {
                        **common_opts['http_headers'],
                        'Referer': 'https://www.pinterest.com/'
                    }

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

                if os.path.exists(file_name):
                    baixou = True
                    break
            except Exception as e:
                ultimo_erro = str(e)
                print(f"[TENTATIVA FALHOU] formato={fmt} | url={url} | erro={e}")

        if not baixou:
            raise Exception(ultimo_erro or "Falha ao baixar")

        if os.path.exists(file_name):
            with open(file_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="👉 Download concluído! Aqui está seu vídeo 👊")
            
            if not vip_status:
                # Incrementa e verifica se acabou de chegar no 5
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
                novo_count = user.get("downloads_hoje", 0) + 1
                bot.send_message(message.chat.id, f"📊 Uso diário: {novo_count}/5")
                
                # Se este foi o 5º download, já oferece o VIP imediatamente
                if novo_count >= 5:
                    bot.send_message(message.chat.id, "⚠️ **Você atingiu seu limite diário (5/5)!**\nPara continuar baixando de forma ilimitada agora mesmo, escolha um plano VIP: 👇")
                    mostrar_planos(message)
        
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        print(f"[ERRO DOWNLOAD] URL: {url} | ERRO: {e}")
        try:
            bot.edit_message_text("❌ Erro no link ou formato.", message.chat.id, status_msg.message_id)
        except:
            bot.send_message(message.chat.id, "❌ Erro no link ou formato.")
    finally:
        if os.path.exists(file_name):
            try:
                os.remove(file_name)
            except:
                pass

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
