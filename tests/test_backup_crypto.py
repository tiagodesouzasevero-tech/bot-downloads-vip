import os
import tempfile
import unittest
from pathlib import Path

from backup_crypto import (
    BackupCryptoError,
    MAGIC,
    criptografar_bytes_backup,
    descriptografar_bytes_backup,
    criptografar_arquivo_backup,
    descriptografar_arquivo_backup,
    validar_segredo_backup,
)


class BackupCryptoTests(unittest.TestCase):
    SEGREDO = "segredo-de-backup-de-teste-com-mais-de-32-bytes-123456"

    def test_segredo_forte_e_aceito(self):
        self.assertTrue(validar_segredo_backup(self.SEGREDO))

    def test_segredo_curto_e_rejeitado(self):
        self.assertFalse(validar_segredo_backup("curto"))

    def test_roundtrip_preserva_bytes(self):
        original = b'{"usuarios": [1, 2], "vip": true}'
        cifrado = criptografar_bytes_backup(original, self.SEGREDO)
        self.assertTrue(cifrado.startswith(MAGIC))
        self.assertEqual(descriptografar_bytes_backup(cifrado, self.SEGREDO), original)

    def test_plaintext_nao_aparece_no_arquivo_cifrado(self):
        original = b"DADO-SENSIVEL-NAO-PODE-APARECER-EM-TEXTO-PURO"
        cifrado = criptografar_bytes_backup(original, self.SEGREDO)
        self.assertNotIn(original, cifrado)

    def test_mesmo_backup_gera_ciphertexts_diferentes(self):
        original = b"mesmo-conteudo"
        a = criptografar_bytes_backup(original, self.SEGREDO)
        b = criptografar_bytes_backup(original, self.SEGREDO)
        self.assertNotEqual(a, b)
        self.assertEqual(descriptografar_bytes_backup(a, self.SEGREDO), original)
        self.assertEqual(descriptografar_bytes_backup(b, self.SEGREDO), original)

    def test_chave_errada_nao_abre(self):
        cifrado = criptografar_bytes_backup(b"segredo", self.SEGREDO)
        with self.assertRaises(BackupCryptoError):
            descriptografar_bytes_backup(
                cifrado,
                "outra-chave-de-backup-com-mais-de-32-bytes-abcdef123456",
            )

    def test_arquivo_alterado_nao_abre(self):
        cifrado = bytearray(criptografar_bytes_backup(b"segredo", self.SEGREDO))
        cifrado[-1] ^= 0x01
        with self.assertRaises(BackupCryptoError):
            descriptografar_bytes_backup(bytes(cifrado), self.SEGREDO)

    def test_formato_invalido_nao_abre(self):
        with self.assertRaises(BackupCryptoError):
            descriptografar_bytes_backup(b"nao-e-backup", self.SEGREDO)

    def test_roundtrip_em_arquivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            origem = pasta / "backup.json"
            cifrado = pasta / "backup.bdvbak"
            restaurado = pasta / "restaurado.json"
            origem.write_bytes(b'{"ok": true}')
            criptografar_arquivo_backup(str(origem), str(cifrado), self.SEGREDO)
            descriptografar_arquivo_backup(str(cifrado), str(restaurado), self.SEGREDO)
            self.assertEqual(restaurado.read_bytes(), origem.read_bytes())


if __name__ == "__main__":
    unittest.main()
