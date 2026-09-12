from __future__ import annotations

import copy
import re
import secrets
from collections import Counter

from bson import json_util
from bson.json_util import CANONICAL_JSON_OPTIONS


TEMP_DB_PREFIX = "restore_test_bdv_"
RESTORE_COLLECTIONS = {
    "usuarios": "usuarios",
    "pedidos": "pedidos",
    "metricas_diarias": "metricas_diarias",
    "auditoria_admin": "auditoria_admin",
    "auditoria_sistema": "auditoria_sistema",
}


class RestoreTestError(RuntimeError):
    pass


def _canonical_document(documento: dict) -> str:
    return json_util.dumps(
        documento,
        json_options=CANONICAL_JSON_OPTIONS,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _multiset_canonical(documentos) -> Counter:
    return Counter(_canonical_document(doc) for doc in documentos)


def gerar_nome_banco_temporario() -> str:
    return TEMP_DB_PREFIX + secrets.token_hex(8)


def validar_nome_banco_temporario(nome: str, banco_producao: str) -> str:
    nome = str(nome or "").strip()
    banco_producao = str(banco_producao or "").strip()

    if not banco_producao:
        raise RestoreTestError("Nome do banco de produção ausente.")
    if banco_producao.startswith(TEMP_DB_PREFIX):
        raise RestoreTestError(
            "Banco de produção usa prefixo reservado para testes de restauração."
        )
    if nome == banco_producao:
        raise RestoreTestError("Restauração no banco de produção é proibida.")
    if not re.fullmatch(r"restore_test_bdv_[0-9a-f]{16}", nome):
        raise RestoreTestError("Nome do banco temporário fora do padrão seguro.")
    return nome


def validar_payload_para_restore(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise RestoreTestError("Payload de backup inválido.")
    if int(payload.get("schema_version") or 0) != 3:
        raise RestoreTestError("Teste real exige backup schema 3.")
    if payload.get("serialization") != "mongodb_extended_json_canonical":
        raise RestoreTestError("Serialização Extended JSON inválida.")
    if payload.get("backup_type") != "geral":
        raise RestoreTestError("Teste real exige backup geral.")

    for secao in (*RESTORE_COLLECTIONS.keys(), "vips_ativos"):
        if not isinstance(payload.get(secao), list):
            raise RestoreTestError(f"Seção inválida no backup: {secao}")


def _criar_indices_essenciais_sem_ttl(db_temp) -> None:
    # Índices que validam a compatibilidade estrutural sem acionar TTLs,
    # que poderiam apagar documentos durante o próprio teste.
    db_temp["usuarios"].create_index("vip_ate")
    db_temp["usuarios"].create_index("ultima_data")

    db_temp["pedidos"].create_index("order_nsu", unique=True)
    db_temp["pedidos"].create_index("status")
    db_temp["pedidos"].create_index("user_id")
    db_temp["pedidos"].create_index(
        [("user_id", 1), ("status", 1), ("created_at", -1)]
    )
    db_temp["pedidos"].create_index([("provider", 1), ("txid", 1)])

    db_temp["auditoria_admin"].create_index("created_at")
    db_temp["auditoria_admin"].create_index(
        [("target_user_id", 1), ("created_at", -1)]
    )
    db_temp["auditoria_admin"].create_index(
        [("action", 1), ("status", 1), ("created_at", -1)]
    )

    db_temp["auditoria_sistema"].create_index("created_at")
    db_temp["auditoria_sistema"].create_index(
        [("event_type", 1), ("status", 1), ("created_at", -1)]
    )


def restaurar_em_banco_temporario(client, banco_producao: str, payload: dict) -> dict:
    """Restaura um backup geral em DB isolado, valida e apaga ao final.

    Nunca recebe um nome de destino externo: o nome temporário é gerado
    internamente e precisa passar por uma allowlist rígida.
    """
    validar_payload_para_restore(payload)

    nome_temp = validar_nome_banco_temporario(
        gerar_nome_banco_temporario(),
        banco_producao,
    )
    db_temp = client[nome_temp]

    contagens = {}
    integridade_documental = {}
    indices_ok = False
    cleanup_ok = False

    try:
        for secao, colecao in RESTORE_COLLECTIONS.items():
            origem = payload.get(secao) or []
            docs = [copy.deepcopy(doc) for doc in origem]

            if docs:
                db_temp[colecao].insert_many(docs, ordered=True)

            restaurados = list(db_temp[colecao].find({}))
            contagens[secao] = len(restaurados)

            if len(restaurados) != len(origem):
                raise RestoreTestError(
                    f"Contagem divergente em {secao}: "
                    f"{len(origem)} != {len(restaurados)}"
                )

            if _multiset_canonical(restaurados) != _multiset_canonical(origem):
                raise RestoreTestError(
                    f"Conteúdo/tipos BSON divergentes em {secao}."
                )

            integridade_documental[secao] = True

        # vips_ativos é uma visão/subconjunto da coleção usuarios e não deve
        # ser inserida novamente para não duplicar usuários.
        usuarios_ids = {
            str(doc.get("_id"))
            for doc in payload.get("usuarios") or []
        }
        vips_ids = {
            str(doc.get("_id"))
            for doc in payload.get("vips_ativos") or []
        }
        if not vips_ids.issubset(usuarios_ids):
            raise RestoreTestError("VIP ativo ausente da coleção usuarios.")

        _criar_indices_essenciais_sem_ttl(db_temp)
        indices_ok = True

        return {
            "ok": True,
            "database": nome_temp,
            "contagens": contagens,
            "vips_ativos": len(vips_ids),
            "integridade_documental": integridade_documental,
            "indices_essenciais_ok": indices_ok,
            "cleanup_ok": False,  # atualizado conceitualmente no finally
        }
    finally:
        # Trava novamente o nome imediatamente antes da única operação destrutiva.
        validar_nome_banco_temporario(nome_temp, banco_producao)
        client.drop_database(nome_temp)
        cleanup_ok = True

        # Acesso ao objeto DB não recria coleções. Se ainda houver alguma,
        # a limpeza não foi concluída.
        restantes = list(client[nome_temp].list_collection_names())
        if restantes:
            raise RestoreTestError(
                "Banco temporário não foi removido completamente."
            )
