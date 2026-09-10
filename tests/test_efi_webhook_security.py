import ast
import hashlib
import hmac
import ipaddress
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlparse


FUNCOES = {
    "efi_webhook_hash",
    "validar_requisicao_webhook_efi",
    "validar_ip_webhook_efi",
}


def carregar_funcoes_webhook(secret="segredo-teste"):
    source = Path("bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCOES
    ]
    encontrados = {node.name for node in nodes}
    faltando = FUNCOES - encontrados
    if faltando:
        raise AssertionError(
            "Funcoes Efí de webhook nao encontradas: " + ", ".join(sorted(faltando))
        )

    namespace = {
        "EFI_WEBHOOK_SECRET": secret,
        "EFI_WEBHOOK_ALLOWED_IPS": frozenset({"34.193.116.226"}),
        "hashlib": hashlib,
        "hmac": hmac,
        "ipaddress": ipaddress,
        "parse_qsl": parse_qsl,
        "urlparse": urlparse,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "efi_webhook_test", "exec"), namespace)
    return namespace


class EfiWebhookSecurityTests(unittest.TestCase):
    def test_hash_e_deterministico_para_mesmo_segredo(self):
        ns = carregar_funcoes_webhook("abc123")
        primeiro = ns["efi_webhook_hash"]()
        segundo = ns["efi_webhook_hash"]()
        self.assertEqual(primeiro, segundo)
        self.assertEqual(len(primeiro), 64)

    def test_segredos_diferentes_geram_hashes_diferentes(self):
        h1 = carregar_funcoes_webhook("segredo-a")["efi_webhook_hash"]()
        h2 = carregar_funcoes_webhook("segredo-b")["efi_webhook_hash"]()
        self.assertNotEqual(h1, h2)

    def test_hmac_correto_e_aceito(self):
        ns = carregar_funcoes_webhook("segredo-ok")
        token = ns["efi_webhook_hash"]()
        self.assertTrue(
            ns["validar_requisicao_webhook_efi"](
                f"/efi/webhook?hmac={token}&ignorar="
            )
        )

    def test_hmac_incorreto_e_bloqueado(self):
        ns = carregar_funcoes_webhook("segredo-ok")
        self.assertFalse(
            ns["validar_requisicao_webhook_efi"](
                "/efi/webhook?hmac=token-incorreto"
            )
        )

    def test_hmac_ausente_e_bloqueado(self):
        ns = carregar_funcoes_webhook()
        self.assertFalse(ns["validar_requisicao_webhook_efi"]("/efi/webhook"))

    def test_ip_oficial_efi_e_aceito(self):
        ns = carregar_funcoes_webhook()
        self.assertTrue(
            ns["validar_ip_webhook_efi"]({"X-Real-IP": "34.193.116.226"})
        )

    def test_ip_diferente_e_bloqueado(self):
        ns = carregar_funcoes_webhook()
        self.assertFalse(ns["validar_ip_webhook_efi"]({"X-Real-IP": "1.2.3.4"}))

    def test_x_forwarded_for_nao_burla_x_real_ip(self):
        ns = carregar_funcoes_webhook()
        self.assertFalse(
            ns["validar_ip_webhook_efi"](
                {
                    "X-Real-IP": "1.2.3.4",
                    "X-Forwarded-For": "34.193.116.226",
                }
            )
        )

    def test_ip_ausente_e_bloqueado(self):
        ns = carregar_funcoes_webhook()
        self.assertFalse(ns["validar_ip_webhook_efi"]({}))


if __name__ == "__main__":
    unittest.main()
