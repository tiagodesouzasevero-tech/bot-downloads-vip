import json

from bson import json_util
from bson.json_util import CANONICAL_JSON_OPTIONS


BACKUP_SCHEMA_VERSION = 3
BACKUP_SERIALIZATION = "mongodb_extended_json_canonical"


class BackupFormatError(ValueError):
    pass


def dumps_backup_payload(payload: dict) -> str:
    if not isinstance(payload, dict):
        raise BackupFormatError("Payload de backup inválido.")
    if payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise BackupFormatError("Schema de backup atual inválido.")
    if payload.get("serialization") != BACKUP_SERIALIZATION:
        raise BackupFormatError("Serialização de backup atual inválida.")

    return json_util.dumps(
        payload,
        json_options=CANONICAL_JSON_OPTIONS,
        ensure_ascii=False,
        indent=2,
    )


def loads_backup_text(texto: str):
    if not isinstance(texto, str) or not texto.strip():
        raise BackupFormatError("Backup JSON vazio ou inválido.")

    # Faz uma leitura JSON simples apenas para identificar o formato.
    # No Canonical Extended JSON, até inteiros como schema_version são
    # envolvidos por marcadores BSON (ex.: {"$numberInt": "3"}), então a
    # versão não pode ser convertida com int() antes da decodificação BSON.
    bruto = json.loads(texto)
    if not isinstance(bruto, dict):
        raise BackupFormatError("Payload de backup não é um objeto.")

    if bruto.get("serialization") == BACKUP_SERIALIZATION:
        decodificado = json_util.loads(
            texto,
            json_options=CANONICAL_JSON_OPTIONS,
        )
        if not isinstance(decodificado, dict):
            raise BackupFormatError("Payload Extended JSON inválido.")
        if decodificado.get("schema_version") != BACKUP_SCHEMA_VERSION:
            raise BackupFormatError("Schema Extended JSON não suportado.")
        return decodificado

    # Compatibilidade de leitura com backups antigos schema 2, que eram JSON
    # comum e não possuíam o marcador de serialização Extended JSON.
    try:
        versao_legada = int(bruto.get("schema_version") or 0)
    except (TypeError, ValueError):
        versao_legada = 0

    if versao_legada == 2:
        return bruto

    raise BackupFormatError("Schema de backup não suportado.")


def loads_backup_bytes(dados: bytes):
    if not isinstance(dados, (bytes, bytearray)):
        raise BackupFormatError("Conteúdo do backup inválido.")
    return loads_backup_text(bytes(dados).decode("utf-8"))
