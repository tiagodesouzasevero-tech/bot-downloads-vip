import re
import unittest
from pathlib import Path


class BackupEncryptionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codigo = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        inicio = cls.codigo.index("def processar_backup_admin(")
        fim = cls.codigo.index("\ndef _inicializar_estado_backup_automatico():", inicio)
        cls.funcao = cls.codigo[inicio:fim]

    def test_envio_usa_arquivo_criptografado(self):
        self.assertIn("enviar_documento_privado_admin(\n            caminho_criptografado", self.funcao)
        self.assertNotIn("enviar_documento_privado_admin(caminho_arquivo", self.funcao)

    def test_json_puro_e_removido_antes_do_envio(self):
        remover = self.funcao.index("os.remove(caminho_arquivo)")
        enviar = self.funcao.index("enviar_documento_privado_admin(")
        self.assertLess(remover, enviar)

    def test_chave_ausente_nao_faz_fallback_plaintext(self):
        self.assertIn("BACKUP_ENCRYPTION_SECRET_AUSENTE_OU_FRACO", self.funcao)
        self.assertNotIn("fallback_plaintext", self.funcao.lower())

    def test_roundtrip_e_exigido_antes_do_envio(self):
        roundtrip = self.funcao.index("descriptografar_bytes_backup(")
        enviar = self.funcao.index("enviar_documento_privado_admin(")
        self.assertLess(roundtrip, enviar)
        self.assertIn("BACKUP_CRIPTOGRAFADO_ROUNDTRIP_DIVERGENTE", self.funcao)


if __name__ == "__main__":
    unittest.main()
