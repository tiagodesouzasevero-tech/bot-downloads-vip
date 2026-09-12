import unittest
from datetime import datetime, timezone

try:
    from bson import ObjectId
    from backup_format import (
        BACKUP_SCHEMA_VERSION,
        BACKUP_SERIALIZATION,
        BackupFormatError,
        dumps_backup_payload,
        loads_backup_text,
        loads_backup_bytes,
    )
    BSON_DISPONIVEL = True
except ImportError:
    BSON_DISPONIVEL = False


@unittest.skipUnless(BSON_DISPONIVEL, "PyMongo/bson não disponível neste ambiente")
class BackupExtendedJsonTests(unittest.TestCase):
    def payload(self):
        return {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "serialization": BACKUP_SERIALIZATION,
            "generated_at": datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
            "service": "teste",
            "environment": "teste",
            "backup_type": "geral",
            "usuarios_count": 1,
            "vips_ativos_count": 0,
            "pedidos_count": 1,
            "metricas_diarias_count": 0,
            "auditoria_admin_count": 0,
            "auditoria_sistema_count": 0,
            "usuarios": [{
                "_id": "123",
                "created_at": datetime(2026, 9, 1, 10, 20, 30, tzinfo=timezone.utc),
            }],
            "vips_ativos": [],
            "pedidos": [{
                "_id": ObjectId("66d000000000000000000001"),
                "order_nsu": "ord-1",
                "created_at": datetime(2026, 9, 2, 11, 0, tzinfo=timezone.utc),
            }],
            "metricas_diarias": [],
            "auditoria_admin": [],
            "auditoria_sistema": [],
        }

    def test_roundtrip_preserva_datetime(self):
        texto = dumps_backup_payload(self.payload())
        restaurado = loads_backup_text(texto)
        self.assertIsInstance(restaurado["usuarios"][0]["created_at"], datetime)
        self.assertIsInstance(restaurado["pedidos"][0]["created_at"], datetime)

    def test_roundtrip_preserva_objectid(self):
        texto = dumps_backup_payload(self.payload())
        restaurado = loads_backup_text(texto)
        self.assertIsInstance(restaurado["pedidos"][0]["_id"], ObjectId)

    def test_extended_json_contem_marcadores_bson(self):
        texto = dumps_backup_payload(self.payload())
        self.assertIn('"$date"', texto)
        self.assertIn('"$oid"', texto)

    def test_bytes_roundtrip(self):
        texto = dumps_backup_payload(self.payload())
        restaurado = loads_backup_bytes(texto.encode("utf-8"))
        self.assertIsInstance(restaurado["pedidos"][0]["created_at"], datetime)

    def test_schema2_continua_legivel_com_strings(self):
        legado = (
            '{"schema_version":2,"backup_type":"geral",'
            '"usuarios":[{"_id":"1","created_at":"2026-09-01T10:20:30"}]}'
        )
        restaurado = loads_backup_text(legado)
        self.assertEqual(restaurado["schema_version"], 2)
        self.assertIsInstance(restaurado["usuarios"][0]["created_at"], str)

    def test_schema3_sem_serialization_e_rejeitado(self):
        texto = '{"schema_version":3,"backup_type":"geral"}'
        with self.assertRaises(BackupFormatError):
            loads_backup_text(texto)


if __name__ == "__main__":
    unittest.main()
