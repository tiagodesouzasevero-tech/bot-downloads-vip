"""Utilitários de data e hora usados pelo bot.

Mantém o mesmo fuso operacional que já era usado no bot.py.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


TZ = ZoneInfo("America/Sao_Paulo")


def agora_tz():
    return datetime.now(TZ)


def hoje_str():
    return agora_tz().strftime("%Y-%m-%d")


def formatar_validade_vip(vip_ate):
    if vip_ate == "Vitalício":
        return "Vitalício"
    try:
        return datetime.strptime(str(vip_ate), "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(vip_ate or "Ativo")
