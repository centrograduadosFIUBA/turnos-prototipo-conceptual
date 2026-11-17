"""Matriz de Tests Automatizados (spec.md §13): INV-01, INV-02, INV-03, validación del cuerpo y casos de borde, vía HTTP.

Aislamiento de la base:
- La semilla se construye UNA vez por módulo en un directorio temporal (`plantilla`).
- Cada test recibe una COPIA propia de esa base (`api`), así arranca limpio y no ve lo que hicieron otros.
- `config.DB_PATH` apunta a la copia; el `TestClient` se usa sin `with`, de modo que el `lifespan`
  no siembra ni toca ninguna otra base.
- `base_real_intacta` compara la huella SHA-256 de `backend/turnos.db` antes y después del módulo.

El reloj del servidor está fijo en AHORA (miércoles 2026-11-04 10:00, UTC-3) por `conftest.reloj_fijo`.
"""
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import db
import main
import seed
from domain import a_iso
from seed import uid
from tests.conftest import AHORA, como

BASE_REAL = Path(config.__file__).resolve().parent / "turnos.db"
LOCAL = AHORA.astimezone(config.ZONA_OPERACION)

# Test 1 y 2 — mañana (jueves) 12:00 con la Lic. Ibáñez (p3, s5 de 30 min, atiende de 9 a 13).
MANANA = a_iso(LOCAL.replace(hour=12) + timedelta(days=1))
# Test 3 y 4 — hoy 15:00, dentro de 5 h, con la Dra. Martínez (p1, s1 de 30 min, atiende de 14 a 18).
EN_5_HORAS = a_iso(AHORA + timedelta(hours=5))


# ---------------------------------------------------------------- aislamiento
def _huella(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="module", autouse=True)
def base_real_intacta():
    antes = _huella(BASE_REAL)
    yield
    assert _huella(BASE_REAL) == antes, "La suite modificó backend/turnos.db"


@pytest.fixture(scope="module")
def plantilla(tmp_path_factory) -> Path:
    """Esquema de spec §4.1 + semilla, construidos una sola vez por módulo."""
    path = tmp_path_factory.mktemp("plantilla") / "turnos.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        seed.sembrar(conn, AHORA)
    return path


@pytest.fixture
def api(plantilla, tmp_path, monkeypatch) -> TestClient:
    """Cliente HTTP sobre una copia limpia de la plantilla, exclusiva de este test."""
    path = tmp_path / "turnos.db"
    with closing(sqlite3.connect(plantilla)) as origen, closing(sqlite3.connect(path)) as destino:
        origen.backup(destino)
    assert path.resolve() != BASE_REAL
    monkeypatch.setattr(config, "DB_PATH", path)
    return TestClient(main.app)


# ---------------------------------------------------------------- utilidades
def reservar(api, quien: str, servicio: str, inicio: str):
    return api.post("/api/turnos", json={"servicio_id": uid(servicio), "inicio": inicio}, headers=como(quien))


def cancelar(api, quien: str, turno_id: str):
    return api.post(f"/api/turnos/{turno_id}/cancelar", json={}, headers=como(quien))


def codigo(r) -> str:
    return r.json()["error"]["codigo"]


def turnos_en(api, quien: str, inicio: str) -> list[dict]:
    r = api.get("/api/turnos", headers=como(quien))
    assert r.status_code == 200, r.text
    return [t for t in r.json() if t["inicio"] == inicio]


def ver_turno(api, quien: str, turno_id: str) -> dict:
    r = api.get("/api/turnos", headers=como(quien))
    assert r.status_code == 200, r.text
    (turno,) = [t for t in r.json() if t["id"] == turno_id]
    return turno


def contar_turnos() -> int:
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        return conn.execute("SELECT COUNT(*) FROM turno").fetchone()[0]


# ---------------------------------------------------------------- Test 1 · camino feliz + INV-03
def test_1_reserva_valida_para_manana_aparece_al_listar(api):
    r = reservar(api, "c1", "s5", MANANA)
    assert r.status_code == 201, r.text
    creado = r.json()
    assert creado["estado"] == "CONFIRMADO" and creado["inicio"] == MANANA
    assert r.headers["location"] == f"/api/turnos/{creado['id']}"

    # INV-03: otro cliente HTTP (otra conexión a la base) lo devuelve igual…
    assert turnos_en(TestClient(main.app), "c1", MANANA) == [creado]
    # …y quedó escrito en el archivo SQLite, no solo en memoria.
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        assert conn.execute("SELECT estado FROM turno WHERE id = ?", (creado["id"],)).fetchone() == ("CONFIRMADO",)


# ---------------------------------------------------------------- Test 2 · INV-02
def test_2_mismo_horario_rechaza_la_segunda_reserva(api):
    assert reservar(api, "c1", "s5", MANANA).status_code == 201
    antes = contar_turnos()

    r = reservar(api, "c3", "s5", MANANA)

    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"
    assert contar_turnos() == antes                                   # no se persistió nada
    assert [t["cliente_id"] for t in turnos_en(api, "p3", MANANA)] == [uid("c1")]


# ---------------------------------------------------------------- Test 3 · INV-01, cancelación en término
def test_3_cancelar_con_5_horas_de_anticipacion(api):
    turno = reservar(api, "c1", "s1", EN_5_HORAS).json()

    r = cancelar(api, "c1", turno["id"])

    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CANCELADO" and r.json()["cancelado_por_id"] == uid("c1")


# ---------------------------------------------------------------- Test 4 · INV-01, cancelación tardía
def test_4_cancelar_a_45_minutos_del_inicio_es_rechazado(api, reloj_fijo):
    # RN-04 exige 1 h de antelación para reservar: un turno a 45 min no se puede CREAR por la API.
    # Se crea a 5 h y se adelanta el reloj del servidor hasta que faltan 45 min.
    turno = reservar(api, "c1", "s1", EN_5_HORAS).json()
    reloj_fijo.valor = datetime.fromisoformat(EN_5_HORAS) - timedelta(minutes=45)

    r = cancelar(api, "c1", turno["id"])

    assert r.status_code == 409 and codigo(r) == "CANCELLATION_WINDOW_EXPIRED"
    assert ver_turno(api, "c1", turno["id"])["estado"] == "CONFIRMADO"   # sigue igual en la base


# ---------------------------------------------------------------- Test 5 · validación Pydantic
@pytest.mark.parametrize("cuerpo", [
    pytest.param({}, id="cuerpo-vacio"),
    pytest.param({"inicio": MANANA}, id="falta-servicio_id"),
    pytest.param({"servicio_id": uid("s5")}, id="falta-inicio"),
    pytest.param({"servicio_id": 123, "inicio": MANANA}, id="servicio_id-no-texto"),
    pytest.param({"servicio_id": uid("s5"), "inicio": "mañana a las 12"}, id="inicio-no-fecha"),
])
def test_5_cuerpo_invalido_es_rechazado_por_pydantic(api, cuerpo):
    antes = contar_turnos()

    r = api.post("/api/turnos", json=cuerpo, headers=como("c1"))

    assert r.status_code == 422 and codigo(r) == "VALIDATION_ERROR"
    assert contar_turnos() == antes


# ---------------------------------------------------------------- Test 6 · textos vacíos o en blanco
@pytest.mark.parametrize("cuerpo", [
    pytest.param({"servicio_id": "", "inicio": MANANA}, id="servicio_id-vacio"),
    pytest.param({"servicio_id": "   ", "inicio": MANANA}, id="servicio_id-espacios"),
    pytest.param({"servicio_id": uid("s5"), "inicio": ""}, id="inicio-vacio"),
    pytest.param({"servicio_id": uid("s5"), "inicio": "   "}, id="inicio-espacios"),
    pytest.param({"servicio_id": uid("s5"), "inicio": MANANA, "cliente_id": " "}, id="cliente_id-espacio"),
])
def test_6_textos_vacios_o_en_blanco_no_crean_turnos(api, cuerpo):
    antes = contar_turnos()

    r = api.post("/api/turnos", json=cuerpo, headers=como("c1"))

    assert r.status_code == 422 and codigo(r) == "VALIDATION_ERROR"
    assert contar_turnos() == antes


# ---------------------------------------------------------------- Test 7 · cancelar un turno inexistente
@pytest.mark.parametrize("quien,turno_id", [
    pytest.param("c1", uid("t-inexistente"), id="cliente-uuid-inexistente"),
    pytest.param("c1", "no-es-un-id", id="cliente-id-arbitrario"),
    pytest.param("admin", uid("t-inexistente"), id="admin-uuid-inexistente"),
])
def test_7_cancelar_turno_inexistente_devuelve_404(api, quien, turno_id):
    r = api.post(f"/api/turnos/{turno_id}/cancelar", json={"motivo": "Prueba"}, headers=como(quien))

    assert r.status_code == 404 and codigo(r) == "NOT_FOUND"


# ---------------------------------------------------------------- Test 8 · cancelar dos veces
def test_8_cancelar_un_turno_ya_cancelado_es_rechazado(api):
    turno = reservar(api, "c1", "s1", EN_5_HORAS).json()
    primera = cancelar(api, "c1", turno["id"])
    assert primera.status_code == 200

    r = cancelar(api, "c1", turno["id"])

    assert r.status_code == 409 and codigo(r) == "INVALID_STATE_TRANSITION"   # RN-06: CANCELADO es terminal
    assert ver_turno(api, "c1", turno["id"]) == primera.json()               # la segunda no cambió nada
