"""Criptografia autenticada dos backups do bot Baixar Vídeos HD.

Formato .bdvbak v1:
    magic(8) + salt(16) + nonce(12) + AES-GCM(ciphertext+tag)

A chave AES-256 é derivada do segredo dedicado por scrypt. Cada arquivo usa
salt e nonce aleatórios, então backups iguais não geram ciphertext igual.
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"BDVIPBK1"
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32
MIN_SECRET_BYTES = 32
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
AAD = b"bot-downloads-vip:backup:v1"


class BackupCryptoError(RuntimeError):
    pass


def _normalizar_segredo(segredo: str) -> bytes:
    valor = str(segredo or "").strip().encode("utf-8")
    if len(valor) < MIN_SECRET_BYTES:
        raise BackupCryptoError(
            f"BACKUP_ENCRYPTION_SECRET deve ter pelo menos {MIN_SECRET_BYTES} bytes."
        )
    return valor


def validar_segredo_backup(segredo: str) -> bool:
    try:
        _normalizar_segredo(segredo)
        return True
    except BackupCryptoError:
        return False


def _derivar_chave(segredo: str, salt: bytes) -> bytes:
    material = _normalizar_segredo(segredo)
    if not isinstance(salt, bytes) or len(salt) != SALT_SIZE:
        raise BackupCryptoError("Salt de backup inválido.")
    kdf = Scrypt(
        salt=salt,
        length=KEY_SIZE,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return kdf.derive(material)


def criptografar_bytes_backup(dados: bytes, segredo: str) -> bytes:
    if not isinstance(dados, (bytes, bytearray)):
        raise BackupCryptoError("Conteúdo do backup deve ser bytes.")
    salt = secrets.token_bytes(SALT_SIZE)
    nonce = secrets.token_bytes(NONCE_SIZE)
    chave = _derivar_chave(segredo, salt)
    cifrado = AESGCM(chave).encrypt(nonce, bytes(dados), AAD)
    return MAGIC + salt + nonce + cifrado


def descriptografar_bytes_backup(blob: bytes, segredo: str) -> bytes:
    if not isinstance(blob, (bytes, bytearray)):
        raise BackupCryptoError("Arquivo criptografado inválido.")
    blob = bytes(blob)
    minimo = len(MAGIC) + SALT_SIZE + NONCE_SIZE + 16
    if len(blob) < minimo or not blob.startswith(MAGIC):
        raise BackupCryptoError("Formato .bdvbak inválido ou versão não suportada.")

    pos = len(MAGIC)
    salt = blob[pos:pos + SALT_SIZE]
    pos += SALT_SIZE
    nonce = blob[pos:pos + NONCE_SIZE]
    pos += NONCE_SIZE
    cifrado = blob[pos:]
    chave = _derivar_chave(segredo, salt)

    try:
        return AESGCM(chave).decrypt(nonce, cifrado, AAD)
    except InvalidTag as exc:
        raise BackupCryptoError(
            "Não foi possível abrir o backup: chave incorreta ou arquivo alterado."
        ) from exc


def _gravar_atomico_privado(caminho: str | os.PathLike[str], dados: bytes) -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp-" + secrets.token_hex(6))
    try:
        with open(temporario, "wb") as arquivo:
            try:
                os.chmod(temporario, 0o600)
            except OSError:
                pass
            arquivo.write(dados)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
    finally:
        if temporario.exists():
            try:
                temporario.unlink()
            except OSError:
                pass


def criptografar_arquivo_backup(caminho_json: str, caminho_saida: str, segredo: str) -> str:
    with open(caminho_json, "rb") as arquivo:
        original = arquivo.read()
    cifrado = criptografar_bytes_backup(original, segredo)
    _gravar_atomico_privado(caminho_saida, cifrado)
    return str(caminho_saida)


def descriptografar_arquivo_backup(caminho_entrada: str, caminho_saida: str, segredo: str) -> str:
    with open(caminho_entrada, "rb") as arquivo:
        blob = arquivo.read()
    original = descriptografar_bytes_backup(blob, segredo)
    _gravar_atomico_privado(caminho_saida, original)
    return str(caminho_saida)


def _saida_padrao(caminho: Path) -> Path:
    if caminho.name.endswith(".bdvbak"):
        return caminho.with_name(caminho.name[:-7] + ".json")
    return caminho.with_name(caminho.name + ".json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Descriptografa backups .bdvbak do bot Baixar Vídeos HD."
    )
    parser.add_argument("arquivo", help="Arquivo .bdvbak recebido no Telegram")
    parser.add_argument("--saida", help="Caminho do JSON restaurado")
    args = parser.parse_args()

    entrada = Path(args.arquivo)
    saida = Path(args.saida) if args.saida else _saida_padrao(entrada)
    segredo = str(os.environ.get("BACKUP_ENCRYPTION_SECRET") or "").strip()
    if not segredo:
        segredo = getpass.getpass("Chave BACKUP_ENCRYPTION_SECRET: ")

    try:
        descriptografar_arquivo_backup(str(entrada), str(saida), segredo)
    except (OSError, BackupCryptoError) as exc:
        print(f"Erro: {exc}")
        return 1

    print(f"Backup descriptografado com sucesso: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
