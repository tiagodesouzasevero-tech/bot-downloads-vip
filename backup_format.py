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

    # Primeiro lê somente a estrutura JSON para descobrir a versão.
    bruto = json.loads(texto)
    if not isinstance(bruto, dict):
        raise BackupFormatError("Payload de backup não é um objeto.")

    try:
        versao = int(bruto.get("schema_version") or 0)
    except (TypeError, ValueError):
        versao = 0

    # Schema 3+: Extended JSON canônico, que recupera datetime/ObjectId/Binary.
    if versao >= BACKUP_SCHEMA_VERSION:
        if bruto.get("serialization") != BACKUP_SERIALIZATION:
            raise BackupFormatError("Serialização Extended JSON ausente ou inválida.")
        return json_util.loads(
            texto,
            json_options=CANONICAL_JSON_OPTIONS,
        )

    # Compatibilidade de leitura com backups antigos schema 2.
    return bruto


def loads_backup_bytes(dados: bytes):
    if not isinstance(dados, (bytes, bytearray)):
        raise BackupFormatError("Conteúdo do backup inválido.")
    return loads_backup_text(bytes(dados).decode("utf-8"))
