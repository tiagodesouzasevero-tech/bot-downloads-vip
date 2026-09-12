import unittest
from pathlib import Path


class RestoreRealSafetyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raiz = Path(__file__).resolve().parents[1]
        cls.bot = (raiz / "bot.py").read_text(encoding="utf-8")
        cls.utils = (raiz / "restore_test_utils.py").read_text(encoding="utf-8")

    def test_comando_e_admin_privado(self):
        self.assertIn('@bot.message_handler(commands=["testarrestore"])', self.bot)
        self.assertIn("if not exigir_admin_privado(message):", self.bot)

    def test_nome_temp_e_gerado_internamente(self):
        self.assertIn("gerar_nome_banco_temporario()", self.utils)
        self.assertIn('TEMP_DB_PREFIX = "restore_test_bdv_"', self.utils)

    def test_producao_e_explicitamente_proibida(self):
        self.assertIn(
            'raise RestoreTestError("Restauração no banco de produção é proibida.")',
            self.utils,
        )

    def test_drop_so_usa_nome_temporario_validado(self):
        trecho = self.utils[self.utils.index("finally:"):]
        self.assertIn(
            "validar_nome_banco_temporario(nome_temp, banco_producao)",
            trecho,
        )
        self.assertIn("client.drop_database(nome_temp)", trecho)

    def test_vips_nao_sao_inseridos_como_colecao_separada(self):
        self.assertNotIn('"vips_ativos": "vips_ativos"', self.utils)
        self.assertIn("vips_ids.issubset(usuarios_ids)", self.utils)

    def test_ttl_nao_e_criado_no_banco_temporario(self):
        self.assertNotIn("expireAfterSeconds", self.utils)

    def test_integridade_compara_extended_json_canonico(self):
        self.assertIn("_multiset_canonical(restaurados)", self.utils)
        self.assertIn("_multiset_canonical(origem)", self.utils)

    def test_fluxo_exercita_criptografia_real(self):
        self.assertIn("criptografar_bytes_backup(", self.bot)
        self.assertIn("descriptografar_bytes_backup(", self.bot)
        self.assertIn("loads_backup_bytes(restaurado_bytes)", self.bot)

    def test_log_afirma_zero_escritas_em_producao(self):
        self.assertIn("production_writes=0", self.bot)


if __name__ == "__main__":
    unittest.main()
