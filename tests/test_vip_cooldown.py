import ast
import threading
import unittest
from pathlib import Path


FUNCOES = {
    "registrar_oferta_vip_limite",
    "oferta_vip_limite_em_cooldown",
}


class FakeTime:
    def __init__(self, initial=1000.0):
        self.current = float(initial)

    def monotonic(self):
        return self.current

    def advance(self, seconds):
        self.current += float(seconds)


def carregar_funcoes_cooldown():
    source = Path("bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in FUNCOES
    ]

    encontrados = {node.name for node in nodes}
    faltando = FUNCOES - encontrados
    if faltando:
        raise AssertionError(
            "Funcoes de cooldown nao encontradas no bot.py: "
            + ", ".join(sorted(faltando))
        )

    fake_time = FakeTime()
    namespace = {
        "time": fake_time,
        "VIP_LIMIT_OFFER_LOCK": threading.Lock(),
        "VIP_LIMIT_OFFER_LAST_SHOWN": {},
        "VIP_LIMIT_OFFER_COOLDOWN_SECONDS": 30 * 60,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, "bot_cooldown_test", "exec"), namespace)
    return namespace, fake_time


class VipLimitOfferCooldownTests(unittest.TestCase):
    def setUp(self):
        self.ns, self.clock = carregar_funcoes_cooldown()
        self.registrar = self.ns["registrar_oferta_vip_limite"]
        self.em_cooldown = self.ns["oferta_vip_limite_em_cooldown"]

    def test_usuario_novo_nao_esta_em_cooldown(self):
        self.assertFalse(self.em_cooldown("123"))

    def test_registro_ativa_cooldown(self):
        self.registrar("123")
        self.assertTrue(self.em_cooldown("123"))

    def test_cooldown_continua_antes_de_30_minutos(self):
        self.registrar("123")
        self.clock.advance((30 * 60) - 1)
        self.assertTrue(self.em_cooldown("123"))

    def test_cooldown_expira_em_30_minutos(self):
        self.registrar("123")
        self.clock.advance(30 * 60)
        self.assertFalse(self.em_cooldown("123"))

    def test_usuarios_sao_independentes(self):
        self.registrar("123")
        self.assertTrue(self.em_cooldown("123"))
        self.assertFalse(self.em_cooldown("456"))


if __name__ == "__main__":
    unittest.main()
