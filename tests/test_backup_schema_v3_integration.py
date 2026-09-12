import unittest
from pathlib import Path


class BackupSchemaV3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raiz = Path(__file__).resolve().parents[1]
        cls.bot = (raiz / "bot.py").read_text(encoding="utf-8")
        cls.formato = (raiz / "backup_format.py").read_text(encoding="utf-8")

    def test_bot_nao_converte_datetime_para_iso_manual(self):
        self.assertNotIn("def serializar_para_json(", self.bot)

    def test_payload_atual_usa_schema_v3(self):
        self.assertIn('"schema_version": BACKUP_SCHEMA_VERSION', self.bot)
        self.assertIn('"serialization": BACKUP_SERIALIZATION', self.bot)

    def test_salvamento_usa_extended_json(self):
        self.assertIn("texto_backup = dumps_backup_payload(payload)", self.bot)

    def test_releitura_do_disco_reconstroi_bson(self):
        self.assertIn("payload_relido = loads_backup_text(f.read())", self.bot)
        self.assertIn("relido = loads_backup_text(f.read())", self.bot)

    def test_roundtrip_criptografado_reconstroi_bson(self):
        self.assertIn(
            "relido_criptografado = loads_backup_bytes(restaurado_bytes)",
            self.bot,
        )

    def test_formato_mantem_compatibilidade_schema2(self):
        self.assertIn(
            'if bruto.get("serialization") == BACKUP_SERIALIZATION:',
            self.formato,
        )
        self.assertIn("versao_legada = int(", self.formato)
        self.assertIn("if versao_legada == 2:", self.formato)
        self.assertIn("return bruto", self.formato)


if __name__ == "__main__":
    unittest.main()
