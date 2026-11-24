"""Compatibilidad frontend <-> backend (prototipo-turnos.html <-> main.py).

Dos niveles:
  * Contrato estático: el HTML y la API coinciden en rutas, campos, ids de la semilla y códigos de error.
  * Integración: `frontend_harness.cjs` ejecuta el código REAL del frontend (Node) contra un uvicorn propio,
    con base temporal (nunca toca `turnos.db`) y en un puerto libre.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

RAIZ = Path(__file__).resolve().parent.parent
HTML = (RAIZ / "prototipo-turnos.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "turnos_test.db")
    with TestClient(main.app) as c:
        yield c


# --------------------------------------------------------------------------
# Contrato estático
# --------------------------------------------------------------------------
def test_el_frontend_apunta_al_puerto_del_backend():
    assert "const API_URL = 'http://localhost:8001';" in HTML


def test_las_rutas_que_usa_el_frontend_existen_en_la_api():
    usadas = set(re.findall(r"\$\{API_URL\}(/api/[\w/{}$.-]+)|callApi\(['`](/api/[\w/{}$.-]+)", HTML))
    rutas = {a or b for a, b in usadas}
    rutas = {re.sub(r"\$\{\w+\}", "{turno_id}", r) for r in rutas}
    assert rutas == {"/api/turnos", "/api/turnos/{turno_id}/cancelar", "/api/chat", "/api/conocimiento",  # + Fase 3 (spec §15)
                     "/api/audit-logs", "/api/webhooks/externo"}  # + confiabilidad (spec §16.5)
    assert rutas <= set(main.app.openapi()["paths"])


def test_los_campos_que_lee_el_frontend_los_devuelve_la_api():
    bloque = re.search(r"const turnoFromApi = .*?\n\}\);", HTML, re.S).group(0)
    leidos = set(re.findall(r"\bt\.(\w+)", bloque))
    assert leidos, "no se encontraron campos en turnoFromApi"
    assert leidos <= set(main.TurnoOut.model_fields)


def test_los_campos_que_envia_el_frontend_los_acepta_la_api():
    reserva = re.search(r"callApi\('/api/turnos', \{(.*?)\}\)", HTML).group(1)
    cancelar = re.search(r"cancelar`, \{(.*?)\}\)", HTML).group(1)
    enviados_reserva = set(re.findall(r"(\w+):", reserva))
    enviados_cancelar = set(re.findall(r"(\w+):", cancelar))
    assert enviados_reserva == set(main.TurnoCreate.model_fields)
    assert enviados_cancelar == set(main.CancelarIn.model_fields)


def test_los_ids_de_la_semilla_coinciden_con_el_frontend():
    usuarios = set(re.findall(r"\{ id: '(\w+)', role: '(\w+)', nombre: '([^']+)'", HTML))
    esperados = {(i, r, n) for (i, r, n, *_resto) in main.SEED_USERS}
    assert usuarios == esperados

    servicios = set(re.findall(r"\{ id: '(s\d+)', profesionalId: '(\w+)', nombre: '([^']+)'.*?duracionMin: (\d+)", HTML))
    esperados = {(i, p, n, str(m)) for (i, p, n, _d, m, _pr) in main.SEED_SERVICES}
    assert servicios == esperados


def test_el_frontend_conoce_todos_los_codigos_de_error_del_backend():
    fuente = Path(main.__file__).read_text(encoding="utf-8")
    codigos = set(re.findall(r'DomainError\(\s*\d+,\s*"([A-Z_]+)"', fuente)) | {"INVALID_REQUEST"}
    conocidos = set(re.findall(r"\b([A-Z][A-Z_]{4,}):\s*\d+", re.search(r"const HTTP = \{.*?\};", HTML, re.S).group(0)))
    assert codigos <= conocidos, f"El frontend no conoce: {codigos - conocidos}"


def test_codigos_http_del_frontend_coinciden_con_los_del_backend(client):
    """El mapa HTTP del frontend debe coincidir con el status real que devuelve la API."""
    mapa = {k: int(v) for k, v in re.findall(r"\b([A-Z][A-Z_]{4,}):\s*(\d+)", re.search(r"const HTTP = \{.*?\};", HTML, re.S).group(0))}
    resp = client.post("/api/turnos/no-existe/cancelar", json={"cancelado_por_id": "c1"})
    assert resp.status_code == mapa[resp.json()["error"]]
    resp = client.post("/api/turnos", json={})
    assert resp.status_code == mapa[resp.json()["error"]]


def test_cors_permite_abrir_el_html_desde_otro_origen(client):
    """Abierto con doble clic (file://) el origen es `null`; el navegador exige CORS en el preflight."""
    for origen in ("null", "http://localhost:5500"):
        resp = client.options("/api/turnos", headers={
            "Origin": origen, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "*"
    assert client.get("/api/turnos", headers={"Origin": "null"}).headers["access-control-allow-origin"] == "*"


def test_la_ruta_raiz_sirve_el_frontend(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.content == (RAIZ / "prototipo-turnos.html").read_bytes()


# --------------------------------------------------------------------------
# Integración: código real del frontend contra un backend vivo
# --------------------------------------------------------------------------
integracion = pytest.mark.integracion  # más lentas (levantan uvicorn y Node): pytest -m "not integracion" las omite
@pytest.fixture(scope="module")
def resultado_frontend(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node.js no está instalado")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    base = f"http://127.0.0.1:{puerto}"
    db = tmp_path_factory.mktemp("e2e") / "turnos_e2e.db"
    servidor = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(puerto), "--log-level", "warning"],
        cwd=RAIZ, env={**os.environ, "TURNOS_DB": str(db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base}/api/turnos", timeout=0.5)
                break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("El backend de prueba no arrancó")
        proc = subprocess.run([NODE, str(RAIZ / "tests" / "frontend_harness.cjs"), base],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)
    finally:
        servidor.terminate()
        servidor.wait(timeout=10)


@integracion
def test_todos_los_slots_que_ofrece_el_frontend_los_acepta_el_backend(resultado_frontend):
    r = resultado_frontend
    assert r["listaInicial"] == 0
    assert len(r["slotsOfrecidos"]) == 12  # primer y último slot de cada uno de los 6 servicios
    for s in r["slotsOfrecidos"]:
        assert s["ok"], s
        assert s["finCorrecto"] and s["inicioIgual"], s  # fin = inicio + duración; mismo instante de ida y vuelta
        assert s["efectos"] == {"audit": 1, "emails": 1}, s  # la UI procesa la respuesta sin errores


@integracion
def test_el_frontend_reserva_y_relee_la_lista(resultado_frontend):
    r = resultado_frontend
    assert r["reserva"] == {"ok": True, "turnosEnLista": 13, "estado": "CONFIRMADO"}


@integracion
def test_el_frontend_muestra_los_errores_de_reserva_del_backend(resultado_frontend):
    r = resultado_frontend
    assert (r["dobleReserva"]["code"], r["dobleReserva"]["http"]) == ("SLOT_UNAVAILABLE", 409)
    assert (r["emailNoVerificado"]["code"], r["emailNoVerificado"]["http"]) == ("EMAIL_NOT_VERIFIED", 403)
    assert (r["fueraDeGrilla"]["code"], r["fueraDeGrilla"]["http"]) == ("INVALID_TIME_RANGE", 422)
    for clave in ("dobleReserva", "emailNoVerificado", "fueraDeGrilla"):
        assert r[clave]["message"]  # texto legible del backend para el toast


@integracion
def test_el_frontend_cancela_y_muestra_los_errores_de_cancelacion(resultado_frontend):
    r = resultado_frontend
    assert r["cancelOk"] == {"ok": True, "estado": "CANCELADO", "canceladoPor": "c1", "canceladoRol": "CLIENTE",
                             "efectos": {"audit": 1, "emails": 1}}
    assert (r["cancelAjeno"]["code"], r["cancelAjeno"]["http"]) == ("NOT_FOUND", 404)
    assert (r["cancelAdminSinMotivo"]["code"], r["cancelAdminSinMotivo"]["http"]) == ("INVALID_REQUEST", 422)
    assert (r["cancelRepetido"]["code"], r["cancelRepetido"]["http"]) == ("INVALID_STATE_TRANSITION", 409)
    assert (r["cancelInexistente"]["code"], r["cancelInexistente"]["http"]) == ("NOT_FOUND", 404)
    assert r["listaFinal"] == 13  # cancelar no elimina el turno (RN-06)


@integracion
def test_el_frontend_avisa_si_el_backend_no_esta_disponible(resultado_frontend):
    caido = resultado_frontend["backendCaido"]
    assert (caido["code"], caido["http"]) == ("API_NO_DISPONIBLE", 0)
    assert "uvicorn" in caido["message"]
