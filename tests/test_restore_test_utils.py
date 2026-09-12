import copy
import unittest

try:
    from restore_test_utils import (
        RestoreTestError,
        TEMP_DB_PREFIX,
        validar_nome_banco_temporario,
        validar_payload_para_restore,
    )
    MODULO_OK = True
except ImportError:
    MODULO_OK = False


@unittest.skipUnless(MODULO_OK, "bson/PyMongo não disponível neste ambiente")
class RestoreUtilsBehaviorTests(unittest.TestCase):
    def test_nome_producao_e_rejeitado(self):
        with self.assertRaises(RestoreTestError):
            validar_nome_banco_temporario("bot_downloader", "bot_downloader")

    def test_nome_fora_do_prefixo_e_rejeitado(self):
        with self.assertRaises(RestoreTestError):
            validar_nome_banco_temporario("teste_qualquer", "bot_downloader")

    def test_nome_temporario_valido_e_aceito(self):
        nome = TEMP_DB_PREFIX + "0123456789abcdef"
        self.assertEqual(
            validar_nome_banco_temporario(nome, "bot_downloader"),
            nome,
        )

    def test_producao_com_prefixo_reservado_e_rejeitada(self):
        with self.assertRaises(RestoreTestError):
            validar_nome_banco_temporario(
                TEMP_DB_PREFIX + "0123456789abcdef",
                TEMP_DB_PREFIX + "producao",
            )

    def test_schema2_e_rejeitado_no_restore_real(self):
        payload = {
            "schema_version": 2,
            "backup_type": "geral",
            "serialization": None,
        }
        with self.assertRaises(RestoreTestError):
            validar_payload_para_restore(payload)

    def test_schema3_incompleto_e_rejeitado(self):
        payload = {
            "schema_version": 3,
            "serialization": "mongodb_extended_json_canonical",
            "backup_type": "geral",
        }
        with self.assertRaises(RestoreTestError):
            validar_payload_para_restore(payload)


if __name__ == "__main__":
    unittest.main()
