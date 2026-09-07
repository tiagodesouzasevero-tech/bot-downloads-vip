import unittest
from datetime import datetime

from time_utils import TZ, agora_tz, formatar_validade_vip, hoje_str


class TimeUtilsTests(unittest.TestCase):
    def test_timezone_sao_paulo(self):
        self.assertEqual(str(TZ), "America/Sao_Paulo")

    def test_agora_tz_tem_timezone(self):
        atual = agora_tz()
        self.assertIsNotNone(atual.tzinfo)
        self.assertEqual(str(atual.tzinfo), "America/Sao_Paulo")

    def test_hoje_str_formato(self):
        valor = hoje_str()
        datetime.strptime(valor, "%Y-%m-%d")

    def test_formatar_validade_vip_data(self):
        self.assertEqual(formatar_validade_vip("2026-09-30"), "30/09/2026")

    def test_formatar_validade_vip_vitalicio(self):
        self.assertEqual(formatar_validade_vip("Vitalício"), "Vitalício")

    def test_formatar_validade_vip_vazia(self):
        self.assertEqual(formatar_validade_vip(None), "Ativo")


if __name__ == "__main__":
    unittest.main()
