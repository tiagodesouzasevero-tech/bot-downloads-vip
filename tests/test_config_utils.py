import os
import unittest
from unittest.mock import patch

from config_utils import get_env_int, get_env_required, get_first_env


class ConfigUtilsTests(unittest.TestCase):
    def test_required_remove_espacos(self):
        with patch.dict(os.environ, {"TEST_REQUIRED": "  valor  "}, clear=False):
            self.assertEqual(get_env_required("TEST_REQUIRED"), "valor")

    def test_required_falha_quando_ausente(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_REQUIRED_MISSING", None)
            with self.assertRaises(RuntimeError):
                get_env_required("TEST_REQUIRED_MISSING")

    def test_first_env_usa_primeira_variavel_valida(self):
        with patch.dict(
            os.environ,
            {"TEST_FIRST_1": "   ", "TEST_FIRST_2": " segundo "},
            clear=False,
        ):
            self.assertEqual(
                get_first_env(["TEST_FIRST_1", "TEST_FIRST_2"], default="padrao"),
                "segundo",
            )

    def test_first_env_usa_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_FIRST_A", None)
            os.environ.pop("TEST_FIRST_B", None)
            self.assertEqual(
                get_first_env(["TEST_FIRST_A", "TEST_FIRST_B"], default="padrao"),
                "padrao",
            )

    def test_env_int_valida_faixa(self):
        with patch.dict(os.environ, {"TEST_INT": "42"}, clear=False):
            self.assertEqual(get_env_int("TEST_INT", 10, 1, 100), 42)

    def test_env_int_rejeita_abaixo_do_minimo(self):
        with patch.dict(os.environ, {"TEST_INT": "0"}, clear=False):
            with self.assertRaises(RuntimeError):
                get_env_int("TEST_INT", 10, 1, 100)

    def test_env_int_rejeita_acima_do_maximo(self):
        with patch.dict(os.environ, {"TEST_INT": "101"}, clear=False):
            with self.assertRaises(RuntimeError):
                get_env_int("TEST_INT", 10, 1, 100)


if __name__ == "__main__":
    unittest.main()
