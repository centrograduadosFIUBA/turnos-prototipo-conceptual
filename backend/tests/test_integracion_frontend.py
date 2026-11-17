"""Integración frontend ↔ backend: `prototipo-turnos.html` contra el contrato que expone FastAPI.

Lee el HTML del repositorio (no necesita navegador ni servidores levantados) y verifica que:
- `API_BASE` y el origen del frontend coinciden con el puerto y la lista CORS del backend.
- Cada llamada del objeto `Api` existe en el contrato, con el mismo método, y en conjunto cubren todas las rutas.
- Los parámetros de consulta y las claves de los cuerpos que arma el frontend son los que aceptan los schemas.
- Los UUID, usuarios y constantes escritos a mano en el HTML coinciden con `seed.py` y `config.py`.
- El navegador puede hacer cada llamada: preflight CORS con `Content-Type` y `X-Usuario-Id` desde :5500.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import main
import seed
from seed import uid
from tests.conftest import como
from tests.test_turnos import MANANA, api, base_real_intacta, plantilla  # noqa: F401  (fixtures compartidas)

HTML = (Path(__file__).resolve().parents[2] / "prototipo-turnos.html").read_text(encoding="utf-8")
ORIGEN_FRONTEND = "http://localhost:5500"
CONTRATO = main.app.openapi()


# ---------------------------------------------------------------- lectura del HTML
def _bloque_api() -> str:
    """Texto del objeto `const Api = { … };`, donde el frontend define todas sus llamadas."""
    m = re.search(r"const Api = \{(.*?)\n\};", HTML, re.S)
    assert m, "No encontré `const Api = {…}` en prototipo-turnos.html"
    return m.group(1) + "\n"   # el último elemento también termina en salto de línea


def _llamadas_del_frontend() -> list[dict]:
    """Cada `nombre: (…) => api(ruta, { …, method, body })` del objeto Api, con la ruta normalizada."""
    llamadas = []
    for nombre, ruta, opciones in re.findall(r"(\w+): \([^)]*\) =>\s*api\([`'](.*?)[`'], \{(.*?)\}\),?\n", _bloque_api(), re.S):
        metodo = re.search(r"method: '(\w+)'", opciones)
        ruta_base, _, consulta = ruta.partition("?${")   # no confundir con el `?` de un ternario
        cuerpo = re.search(r"body: (.*)", opciones, re.S)
        for ruta_expandida in _expandir(nombre, ruta_base):
            llamadas.append({
                "nombre": nombre,
                "metodo": metodo.group(1) if metodo else "GET",
                "ruta": re.sub(r"\$\{enc\(\w+\)\}", "{id}", ruta_expandida),
                "consulta": sorted(_claves(consulta.split("qs(", 1)[1])) if "qs(" in consulta else [],
                "cuerpo": _claves(cuerpo.group(1)) if cuerpo else set(),
            })
    return llamadas


def _expandir(nombre: str, ruta: str) -> list[str]:
    """Resuelve los tramos dinámicos de la ruta con los valores que usa el frontend."""
    m = re.search(r"\$\{\w+ \? '(\w+)' : '(\w+)'\}", ruta)                      # activar / desactivar
    if m:
        return [ruta.replace(m.group(0), v) for v in m.groups()]
    m = re.search(r"\$\{(?!enc\()(\w+)\}", ruta)                                   # cerrarTurno(…, 'completar')
    if m:
        valores = sorted(set(re.findall(rf"Api\.{nombre}\([^)]*'(\w+)'\)", HTML)))
        assert valores, f"No encontré usos de Api.{nombre} con un valor literal"
        return [ruta.replace(m.group(0), v) for v in valores]
    return [ruta]


def _claves(objeto_js: str) -> set[str]:
    """Claves de un objeto JS literal: `{ clave: valor }`, `{ clave }` y las de un spread condicional.

    Una clave es el identificador que sigue a `{` o `,` y precede a `:`, `,` o `}`; los valores quedan afuera.
    """
    return set(re.findall(r"[{,]\s*(\w+)\s*(?=[:,}])", objeto_js))


def _operacion(metodo: str, ruta: str) -> dict | None:
    """Operación del OpenAPI que atiende esa ruta del frontend (los `{param}` se comparan como comodín)."""
    for plantilla_ruta, ops in CONTRATO["paths"].items():
        if re.fullmatch(re.sub(r"\{\w+\}", "[^/]+", plantilla_ruta), ruta.replace("{id}", "X")):
            return ops.get(metodo.lower())
    return None


def _propiedades_del_cuerpo(op: dict) -> set[str]:
    ref = op["requestBody"]["content"]["application/json"]["schema"]
    ref = ref.get("$ref") or next(s["$ref"] for s in ref.get("anyOf", []) if "$ref" in s)
    return set(CONTRATO["components"]["schemas"][ref.rsplit("/", 1)[1]]["properties"])


LLAMADAS = _llamadas_del_frontend()


def _id_llamada(ll: dict) -> str:
    return f"{ll['nombre']}-{ll['metodo']}-{ll['ruta'].rsplit('/', 1)[-1]}"


# ---------------------------------------------------------------- dirección y CORS
def test_api_base_apunta_al_backend_y_el_frontend_esta_en_cors():
    assert re.search(r"const API_BASE = '([^']+)'", HTML).group(1) == "http://localhost:8000"
    assert {ORIGEN_FRONTEND, "http://127.0.0.1:5500"} <= set(config.CORS_ORIGINS)
    assert {"Content-Type", "X-Usuario-Id"} <= set(config.CORS_HEADERS)                 # los que envía api()
    assert "'Content-Type': 'application/json', 'X-Usuario-Id': actorId" in HTML


# ---------------------------------------------------------------- rutas, consultas y cuerpos
def test_el_frontend_usa_todas_las_rutas_del_contrato():
    usadas = {(ll["metodo"].lower(), re.sub(r"\{\w+\}", "{}", ll["ruta"])) for ll in LLAMADAS}
    contrato = {(m, re.sub(r"\{\w+\}", "{}", p)) for p, ops in CONTRATO["paths"].items() for m in ops}
    assert usadas == contrato, f"Solo en el frontend: {usadas - contrato}. Solo en el backend: {contrato - usadas}"


@pytest.mark.parametrize("llamada", LLAMADAS, ids=_id_llamada)
def test_cada_llamada_del_frontend_existe_y_envia_lo_que_el_backend_acepta(llamada):
    op = _operacion(llamada["metodo"], llamada["ruta"])
    assert op, f"{llamada['metodo']} {llamada['ruta']} no existe en el contrato"

    aceptados = {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}
    assert set(llamada["consulta"]) <= aceptados, f"Parámetros desconocidos: {set(llamada['consulta']) - aceptados}"
    obligatorios = {p["name"] for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")}
    assert obligatorios <= set(llamada["consulta"]), f"Faltan parámetros: {obligatorios - set(llamada['consulta'])}"

    if llamada["cuerpo"]:
        assert "requestBody" in op, "El frontend envía cuerpo y la ruta no lo acepta"
        assert llamada["cuerpo"] <= _propiedades_del_cuerpo(op), \
            f"Campos que el backend rechaza con 422: {llamada['cuerpo'] - _propiedades_del_cuerpo(op)}"


# ---------------------------------------------------------------- datos escritos a mano en el HTML
def test_los_uuid_del_html_son_los_de_la_semilla():
    ids = dict(re.findall(r"(\w+): '([0-9a-f]{8}-[0-9a-f-]{27})'", HTML))
    assert len(ids) == 15
    assert ids == {clave: uid(clave) for clave in ids}


def test_los_usuarios_locales_coinciden_con_la_semilla():
    patron = (r"\{ id: ID\.(\w+), role: '(\w+)', nombre: '([^']+)', email: '([^']+)', "
              r"telefono: '([^']+)', emailVerificado: (true|false) \}")
    del_html = [(k, rol, nom, mail, tel, verif == "true") for k, rol, nom, mail, tel, verif in re.findall(patron, HTML)]
    assert del_html == list(seed.USUARIOS)


def test_las_ayudas_visuales_usan_las_mismas_reglas_que_el_backend():
    valores = dict((k, int(v)) for k, v in re.findall(r"(\w+): (\d+)", re.search(r"const CONFIG = \{([^}]*)\}", HTML).group(1)))
    assert valores == {"CANCEL_WINDOW_H": config.CANCELLATION_WINDOW_HOURS, "MIN_LEAD_H": config.MIN_LEAD_HOURS,
                       "HORIZON_DAYS": config.HORIZON_DAYS, "GRID_MIN": config.GRID_MIN}


# ---------------------------------------------------------------- lo que hace el navegador
@pytest.mark.parametrize("llamada", LLAMADAS, ids=_id_llamada)
def test_el_navegador_puede_hacer_cada_llamada(llamada):
    """Preflight CORS que el navegador envía antes de cada llamada (api() siempre agrega los dos encabezados)."""
    r = TestClient(main.app).options(llamada["ruta"].replace("{id}", uid("x")), headers={
        "Origin": ORIGEN_FRONTEND, "Access-Control-Request-Method": llamada["metodo"],
        "Access-Control-Request-Headers": "content-type,x-usuario-id"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGEN_FRONTEND


def test_reserva_y_cancelacion_tal_como_las_envia_el_navegador(api):
    """Mismos encabezados y cuerpos que `Api.reservar` y `Api.cancelar` (sin motivo → `{}`)."""
    encabezados = {"Origin": ORIGEN_FRONTEND, "Content-Type": "application/json", **como("c1")}

    r = api.post("/api/turnos", json={"servicio_id": uid("s5"), "inicio": MANANA}, headers=encabezados)
    assert r.status_code == 201 and r.headers["access-control-allow-origin"] == ORIGEN_FRONTEND

    r = api.post(f"/api/turnos/{r.json()['id']}/cancelar", json={}, headers=encabezados)
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADO"


def test_post_sin_cuerpo_con_content_type_json_es_aceptado(api):
    """`Api.activarServicio`, `eliminarBloqueo` y `cerrarTurno` mandan `Content-Type: application/json` sin cuerpo."""
    r = api.post(f"/api/servicios/{uid('s6')}/desactivar",
                 headers={"Origin": ORIGEN_FRONTEND, "Content-Type": "application/json", **como("admin")})
    assert r.status_code == 200 and r.json()["activo"] is False
