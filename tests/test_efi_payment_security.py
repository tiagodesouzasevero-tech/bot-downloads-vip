import ast
import hashlib
import logging
import threading
import unittest
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


FUNCOES_PAGAMENTO = {
    "valor_pago_efi_centavos",
    "confirmar_pedido_efi_pago",
}

FUNCOES_VIP = {
    "calcular_nova_data_vip",
    "obter_lock_distribuido_local",
    "liberar_vip_por_plano",
}


class ResultadoMongo:
    def __init__(self, modified_count=0, upserted_id=None):
        self.modified_count = modified_count
        self.upserted_id = upserted_id


def extrair_funcoes(nomes):
    source = Path("bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in nomes
    ]
    encontrados = {node.name for node in nodes}
    faltando = set(nomes) - encontrados
    if faltando:
        raise AssertionError(
            "Funcoes Efí/VIP nao encontradas: " + ", ".join(sorted(faltando))
        )
    return nodes


def carregar_pagamento():
    pedidos_col = Mock()
    agora = datetime(2026, 9, 9, 12, 0, 0)
    namespace = {
        "Decimal": Decimal,
        "InvalidOperation": InvalidOperation,
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "EFI_PAYMENT_VERIFIABLE_STATUSES": frozenset(
            {"awaiting_pix", "processing_efi", "delivery_failed", "expired"}
        ),
        "pedidos_col": pedidos_col,
        "obter_cobranca_efi": Mock(),
        "obter_lock_distribuido_local": lambda _chave, _locks: threading.Lock(),
        "PAYMENT_ORDER_LOCKS": [threading.Lock()],
        "PLANOS": {
            "10.00": {
                "nome": "VIP Mensal",
                "preco_centavos": 1000,
                "dias": 30,
            }
        },
        "liberar_vip_por_plano": Mock(return_value=("2026-10-09", True)),
        "agora_tz": lambda: agora,
        "garantir_vip_de_pedido_pago": Mock(
            return_value={"ok": True, "vip_ate": "2026-10-09"}
        ),
        "_registrar_funil_pago_efi": Mock(),
        "logger": logging.getLogger("efi-payment-test"),
        "referencia_pedido_log": lambda valor: f"ref-{valor}",
    }
    nodes = extrair_funcoes(FUNCOES_PAGAMENTO)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "efi_payment_test", "exec"), namespace)
    return namespace


def pedido_base(**alteracoes):
    pedido = {
        "provider": "efi",
        "order_nsu": "ord-123",
        "txid": "TX123",
        "user_id": "777",
        "plano_key": "10.00",
        "valor_centavos": 1000,
        "status": "awaiting_pix",
    }
    pedido.update(alteracoes)
    return pedido


def cobranca_base(**alteracoes):
    cobranca = {
        "status": "CONCLUIDA",
        "txid": "TX123",
        "pix": [
            {
                "valor": "10.00",
                "horario": "2026-09-09T12:00:00Z",
                "endToEndId": "E123",
            }
        ],
    }
    cobranca.update(alteracoes)
    return cobranca


class EfiPaymentSecurityTests(unittest.TestCase):
    def test_status_nao_concluida_nao_tem_valor_pago(self):
        ns = carregar_pagamento()
        valor, pix = ns["valor_pago_efi_centavos"](
            cobranca_base(status="ATIVA")
        )
        self.assertIsNone(valor)
        self.assertIsNone(pix)

    def test_soma_multiplos_pix_em_centavos(self):
        ns = carregar_pagamento()
        valor, pix = ns["valor_pago_efi_centavos"](
            cobranca_base(
                pix=[
                    {"valor": "4.50", "endToEndId": "E1"},
                    {"valor": "5.50", "endToEndId": "E2"},
                ]
            )
        )
        self.assertEqual(valor, 1000)
        self.assertEqual(pix["endToEndId"], "E1")

    def test_provider_invalido_e_rejeitado(self):
        ns = carregar_pagamento()
        resultado = ns["confirmar_pedido_efi_pago"](
            pedido_base(provider="manual"), cobranca_base()
        )
        self.assertFalse(resultado["pago"])
        self.assertEqual(resultado["motivo"], "pedido_invalido")

    def test_txid_divergente_e_rejeitado(self):
        ns = carregar_pagamento()
        resultado = ns["confirmar_pedido_efi_pago"](
            pedido_base(), cobranca_base(txid="OUTRO-TXID")
        )
        self.assertFalse(resultado["pago"])
        self.assertEqual(resultado["motivo"], "txid_divergente")
        ns["liberar_vip_por_plano"].assert_not_called()

    def test_valor_divergente_e_rejeitado(self):
        ns = carregar_pagamento()
        resultado = ns["confirmar_pedido_efi_pago"](
            pedido_base(),
            cobranca_base(pix=[{"valor": "9.99", "endToEndId": "E1"}]),
        )
        self.assertFalse(resultado["pago"])
        self.assertEqual(resultado["motivo"], "valor_divergente")
        ns["liberar_vip_por_plano"].assert_not_called()

    def test_cobranca_nao_concluida_nao_libera_vip(self):
        ns = carregar_pagamento()
        ns["pedidos_col"].update_one.return_value = ResultadoMongo(1)
        resultado = ns["confirmar_pedido_efi_pago"](
            pedido_base(), cobranca_base(status="ATIVA", pix=[])
        )
        self.assertFalse(resultado["pago"])
        self.assertEqual(resultado["motivo"], "nao_concluida")
        ns["liberar_vip_por_plano"].assert_not_called()

    def test_pagamento_valido_finaliza_e_marca_vip_aplicado(self):
        ns = carregar_pagamento()
        pendente = pedido_base()
        pago = {
            **pendente,
            "status": "paid",
            "vip_aplicado_ao_pedido": True,
            "vip_liberado_ate": "2026-10-09",
        }
        ns["pedidos_col"].find_one.side_effect = [pendente, pago]
        ns["pedidos_col"].update_one.side_effect = [
            ResultadoMongo(1),
            ResultadoMongo(1),
        ]

        resultado = ns["confirmar_pedido_efi_pago"](pendente, cobranca_base())

        self.assertTrue(resultado["pago"])
        self.assertTrue(resultado["finalizado_agora"])
        self.assertEqual(resultado["motivo"], "confirmado")
        ns["liberar_vip_por_plano"].assert_called_once_with(
            "777", ns["PLANOS"]["10.00"], order_nsu="ord-123"
        )

        finalizacao = ns["pedidos_col"].update_one.call_args_list[1].args[1]["$set"]
        self.assertEqual(finalizacao["status"], "paid")
        self.assertEqual(finalizacao["paid_amount"], 1000)
        self.assertTrue(finalizacao["vip_aplicado_ao_pedido"])
        self.assertEqual(finalizacao["efi_status"], "CONCLUIDA")

    def test_pedido_ja_pago_nao_aplica_plano_novamente(self):
        ns = carregar_pagamento()
        pago = pedido_base(
            status="paid",
            vip_aplicado_ao_pedido=True,
            vip_liberado_ate="2026-10-09",
        )
        ns["pedidos_col"].find_one.return_value = pago

        resultado = ns["confirmar_pedido_efi_pago"](pago, cobranca_base())

        self.assertTrue(resultado["pago"])
        self.assertFalse(resultado["finalizado_agora"])
        self.assertEqual(resultado["motivo"], "ja_pago")
        ns["liberar_vip_por_plano"].assert_not_called()
        ns["garantir_vip_de_pedido_pago"].assert_called_once()


class VipOrderIdempotencyTests(unittest.TestCase):
    def test_mesmo_order_nsu_nao_estende_vip_duas_vezes(self):
        usuarios_col = Mock()
        usuario_inicial = {"_id": "777", "vip_ate": None}
        usuario_apos_primeiro = {
            "_id": "777",
            "vip_ate": "2026-10-09",
            "vip_orders_aplicados": ["ord-123"],
        }
        obter_usuario = Mock(side_effect=[usuario_inicial, usuario_apos_primeiro])

        usuarios_col.update_one.side_effect = [
            ResultadoMongo(modified_count=1),
            ResultadoMongo(modified_count=0),
        ]
        usuarios_col.find_one.return_value = usuario_apos_primeiro

        agora = datetime(2026, 9, 9, 12, 0, 0)
        namespace = {
            "datetime": datetime,
            "timedelta": timedelta,
            "hashlib": hashlib,
            "PAYMENT_USER_LOCKS": [threading.Lock() for _ in range(4)],
            "usuarios_col": usuarios_col,
            "obter_usuario": obter_usuario,
            "agora_tz": lambda: agora,
            "hoje_str": lambda: "2026-09-09",
        }
        nodes = extrair_funcoes(FUNCOES_VIP)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "vip_order_test", "exec"), namespace)

        plano = {"dias": 30, "vitalicio": False}
        primeira_data, primeira_aplicacao = namespace["liberar_vip_por_plano"](
            "777", plano, order_nsu="ord-123"
        )
        segunda_data, segunda_aplicacao = namespace["liberar_vip_por_plano"](
            "777", plano, order_nsu="ord-123"
        )

        self.assertEqual(primeira_data, "2026-10-09")
        self.assertTrue(primeira_aplicacao)
        self.assertEqual(segunda_data, "2026-10-09")
        self.assertFalse(segunda_aplicacao)

        segundo_filtro = usuarios_col.update_one.call_args_list[1].args[0]
        self.assertEqual(
            segundo_filtro["vip_orders_aplicados"],
            {"$ne": "ord-123"},
        )


if __name__ == "__main__":
    unittest.main()
