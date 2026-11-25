"""Confiabilidad (spec §16: INV-07, INV-08, INV-09). Sin red: receptor y modelo simulados, base temporal."""
import asyncio
import json
from datetime import timedelta

import anthropic
import httpx
import pytest

import agent
import main
import webhooks
from test_agente import ModeloFalso, client, iso, proximo_slot, respuesta, texto, uso  # noqa: F401 (fixture)

URL = "http://receptor.test/hook"


@pytest.fixture
def receptor(monkeypatch):
    """Receptor simulado. `plan` es la lista de status (o excepciones) a devolver; el último se repite."""
    estado = type("Receptor", (), {"plan": [200], "recibidos": [], "esperas": []})()

    def manejar(request):
        estado.recibidos.append(json.loads(request.content))
        paso = estado.plan.pop(0) if len(estado.plan) > 1 else estado.plan[0]
        if isinstance(paso, Exception):
            raise paso
        return httpx.Response(paso)

    async def dormir(segundos):
        estado.esperas.append(segundos)

    monkeypatch.setenv("WEBHOOK_NOTIFY_URL", URL)
    monkeypatch.setattr(webhooks, "_crear_cliente", lambda: httpx.AsyncClient(transport=httpx.MockTransport(manejar)))
    monkeypatch.setattr(webhooks.asyncio, "sleep", dormir)
    return estado


def filas(tabla):
    with main.read_conn() as conn:
        return [dict(f) for f in conn.execute(f"SELECT * FROM {tabla} ORDER BY rowid").fetchall()]


def reservar(client, delta=timedelta(days=1)):
    return client.post("/api/turnos", json={"cliente_id": "c1", "servicio_id": "s1", "inicio": iso(proximo_slot(delta))})


def pedido_reserva(delta=timedelta(days=1), id_="t1"):
    return respuesta(uso("reservar_turno", {"paciente": "c1", "servicio_id": "s1", "fecha_hora": iso(proximo_slot(delta))}, id_))


# --- Escenarios de aceptación (Clase 7) --------------------------------------
def test_inv07_dos_503_y_un_200_son_3_intentos_y_el_turno_queda_guardado(client, receptor):
    receptor.plan = [503, 503, 200]
    r = reservar(client)

    assert r.status_code == 201
    assert len(receptor.recibidos) == 3 and receptor.esperas == [1, 2]
    [turno] = filas("turno")  # directamente en SQLite
    assert (turno["id"], turno["estado"]) == (r.json()["id"], "CONFIRMADO")
    [entrega] = filas("webhook_logs")
    assert (entrega["estado"], entrega["intentos"], entrega["codigo_http"]) == ("entregado", 3, 200)


def test_inv08_modelo_que_repite_la_misma_llamada_se_corta_en_la_segunda(client):
    class ModeloEnBucle(ModeloFalso):
        def create(self, **kwargs):  # pide siempre lo mismo, sin fin
            self.pedidos.append(kwargs)
            return respuesta(uso("consultar_turnos", {"fecha": "2026-11-25"}, f"t{len(self.pedidos)}"))

    modelo = ModeloEnBucle()
    out = agent.ejecutar_agente("¿qué turnos hay?", client=modelo)

    assert len(modelo.pedidos) == 2  # no hay una tercera llamada al modelo
    assert len(out["tools_usadas"]) == 1  # la repetida no se ejecuta
    assert out["respuesta"] == agent.MENSAJE_CIRCUIT_BREAKER
    [log] = filas("audit_logs")
    assert (log["estado"], log["pasos"], log["herramientas"]) == ("circuit_breaker", 2, '["consultar_turnos"]')


def test_inv09_webhook_entrante_responde_202_y_aparece_en_audit_logs(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(agent, "_crear_cliente", lambda: ModeloFalso(texto("Hola")))
    assert client.get("/api/audit-logs").json() == []

    r = client.post("/api/webhooks/externo",
                    json={"canal": "whatsapp", "remitente": "+5491100000000", "mensaje": "Hola"})

    assert r.status_code == 202 and r.json() == {"status": "procesando"}
    [log] = client.get("/api/audit-logs").json()
    assert (log["origen"], log["prompt"], log["estado"], log["pasos"]) == ("webhook_externo", "Hola", "ok", 1)


# --- INV-07 ------------------------------------------------------------------
def test_reservar_y_cancelar_por_api_notifican(client, receptor):
    turno = reservar(client).json()
    client.post(f"/api/turnos/{turno['id']}/cancelar", json={"cancelado_por_id": "c1"})
    assert [r["evento"] for r in receptor.recibidos] == ["turno.creado", "turno.cancelado"]
    assert receptor.recibidos[0]["turno"] == turno
    assert [(f["estado"], f["intentos"], f["codigo_http"]) for f in filas("webhook_logs")] == [("entregado", 1, 200)] * 2


@pytest.mark.parametrize("fallo", [500, 503, httpx.ConnectError("sin red")])
def test_reintenta_con_espera_exponencial_sin_afectar_el_turno(client, receptor, fallo):
    receptor.plan = [fallo]
    r = reservar(client)
    assert r.status_code == 201 and client.get("/api/turnos").json()[0]["estado"] == "CONFIRMADO"
    assert len(receptor.recibidos) == 4 and receptor.esperas == [1, 2, 4]
    assert [(f["estado"], f["intentos"]) for f in filas("webhook_logs")] == [("fallido", 4)]


def test_se_entrega_en_un_reintento_y_un_4xx_no_se_reintenta(client, receptor):
    receptor.plan = [502, 200]
    reservar(client)
    receptor.plan = [404]
    reservar(client, timedelta(days=2))
    assert [(f["estado"], f["intentos"], f["codigo_http"]) for f in filas("webhook_logs")] == [
        ("entregado", 2, 200), ("fallido", 1, 404)]


def test_cada_intento_se_corta_por_timeout(client, receptor, monkeypatch):
    async def lento(request):
        await asyncio.Event().wait()

    monkeypatch.setattr(webhooks, "TIMEOUT_SEGUNDOS", 0.05)
    monkeypatch.setattr(webhooks, "_crear_cliente", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lento)))
    asyncio.run(webhooks.enviar_notificacion_webhook("turno.creado", {"id": "x"}))
    assert [(f["estado"], f["intentos"], f["error"]) for f in filas("webhook_logs")] == [("fallido", 4, "TimeoutError")]


def test_sin_url_no_envia_ni_guarda(client, receptor, monkeypatch):
    monkeypatch.setenv("WEBHOOK_NOTIFY_URL", "")
    assert reservar(client).status_code == 201
    assert receptor.recibidos == [] and filas("webhook_logs") == []


def test_el_archivo_env_manda_sobre_el_entorno_y_se_relee_en_cada_envio(client, receptor, monkeypatch, tmp_path):
    archivo = tmp_path / ".env"
    monkeypatch.setenv("WEBHOOK_ENV_FILE", str(archivo))
    monkeypatch.setenv("WEBHOOK_NOTIFY_URL", "http://valor-viejo.test/hook")  # como el que deja una terminal

    archivo.write_text(f"WEBHOOK_NOTIFY_URL={URL}\n", encoding="utf-8")
    assert webhooks._url_configurada() == URL
    archivo.write_text("WEBHOOK_NOTIFY_URL=http://otro.test/hook\n", encoding="utf-8")
    assert webhooks._url_configurada() == "http://otro.test/hook"

    archivo.write_text("# WEBHOOK_NOTIFY_URL=http://otro.test/hook\n", encoding="utf-8")
    assert reservar(client).status_code == 201
    assert receptor.recibidos == []  # línea comentada = desactivado, aunque el entorno tenga un valor


def test_una_reserva_rechazada_no_notifica(client, receptor):
    reservar(client)
    assert reservar(client).status_code == 409
    assert len(receptor.recibidos) == 1


def test_la_reserva_del_agente_notifica_aunque_luego_falle_el_modelo(client, receptor, monkeypatch):
    class ModeloQueSeCae(ModeloFalso):
        def create(self, **kwargs):
            if not self.guion:
                raise anthropic.APIConnectionError(request=httpx.Request("POST", "http://modelo.test"))
            return super().create(**kwargs)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(agent, "_crear_cliente", lambda: ModeloQueSeCae(pedido_reserva()))
    r = client.post("/api/chat", json={"mensaje": "reservame", "cliente_id": "c1"})
    assert r.status_code == 503 and r.json()["error"] == "AGENT_UNAVAILABLE"
    assert [e["evento"] for e in receptor.recibidos] == ["turno.creado"]
    [log] = filas("audit_logs")
    assert (log["estado"], log["pasos"], log["herramientas"]) == ("error", 2, '["reservar_turno"]')


# --- INV-08 ------------------------------------------------------------------
def test_llamada_repetida_corta_sin_ejecutarla_ni_volver_al_modelo(client):
    modelo = ModeloFalso(
        respuesta(uso("consultar_turnos", {"fecha": "2030-01-01"})),
        respuesta(uso("consultar_turnos", {"fecha": "2030-01-01"}, "t2")),
        texto("no debería pedirse"),
    )
    out = agent.ejecutar_agente("x", client=modelo)
    assert len(modelo.pedidos) == 2 and len(out["tools_usadas"]) == 1
    assert out["respuesta"] == agent.MENSAJE_CIRCUIT_BREAKER
    assert [(f["estado"], f["pasos"]) for f in filas("audit_logs")] == [("circuit_breaker", 2)]


def test_repeticion_en_la_misma_respuesta_no_duplica_la_reserva(client):
    bloque = pedido_reserva().content[0]
    avisos = []
    out = agent.ejecutar_agente("x", cliente_id="c1", client=ModeloFalso(respuesta(bloque, bloque)),
                                notificar=lambda *a: avisos.append(a))
    assert len(client.get("/api/turnos").json()) == 1 and len(avisos) == 1
    assert out["turnos_modificados"] is True and out["respuesta"] == agent.MENSAJE_CIRCUIT_BREAKER


def test_la_misma_llamada_no_consecutiva_esta_permitida(client):
    a, b = uso("consultar_turnos", {}), uso("consultar_turnos", {"fecha": "2030-01-01"})
    out = agent.ejecutar_agente("x", client=ModeloFalso(respuesta(a), respuesta(b), respuesta(a), texto("listo")))
    assert out["respuesta"] == "listo" and len(out["tools_usadas"]) == 3


# --- INV-09 y endpoints ------------------------------------------------------
def test_chat_deja_una_fila_ok_y_se_lee_por_la_api(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(agent, "_crear_cliente", lambda: ModeloFalso(respuesta(uso("consultar_turnos", {})), texto("ok")))
    client.post("/api/chat", json={"mensaje": "¿qué hay?"})
    [log] = client.get("/api/audit-logs").json()
    assert (log["origen"], log["prompt"], log["herramientas"], log["pasos"], log["estado"]) == (
        "chat_web", "¿qué hay?", ["consultar_turnos"], 2, "ok")
    assert log["latencia_ms"] >= 0


def test_audit_logs_devuelve_las_ultimas_20(client):
    for i in range(23):
        agent.ejecutar_agente(f"m{i}", client=ModeloFalso(texto("ok")))
    assert [f["prompt"] for f in client.get("/api/audit-logs").json()] == [f"m{i}" for i in range(22, 2, -1)]


def test_si_falla_la_auditoria_el_agente_igual_responde(client):
    with main.write_tx() as conn:
        conn.execute("DROP TABLE audit_logs")
    assert agent.ejecutar_agente("x", client=ModeloFalso(texto("ok")))["respuesta"] == "ok"


def test_webhook_externo_responde_202_ejecuta_el_agente_y_notifica(client, receptor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(agent, "_crear_cliente", lambda: ModeloFalso(pedido_reserva(), texto("listo")))
    r = client.post("/api/webhooks/externo", json={"canal": "whatsapp", "remitente": "+54911", "mensaje": "turno para Lucía"})
    assert r.status_code == 202 and r.json() == {"status": "procesando"}
    [log] = filas("audit_logs")  # TestClient espera a que terminen las tareas en segundo plano
    assert (log["origen"], log["prompt"], log["estado"]) == ("webhook_externo", "turno para Lucía", "ok")
    assert [e["evento"] for e in receptor.recibidos] == ["turno.creado"]


def test_webhook_externo_sin_api_key_queda_auditado_como_error(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/webhooks/externo", json={"canal": "whatsapp", "remitente": "a", "mensaje": "hola"})
    assert r.status_code == 202
    assert [(f["origen"], f["estado"], f["pasos"]) for f in filas("audit_logs")] == [("webhook_externo", "error", 0)]


def test_webhook_externo_valida_el_cuerpo(client):
    for cuerpo in ({}, {"canal": "whatsapp", "remitente": "a", "mensaje": "  "}):
        r = client.post("/api/webhooks/externo", json=cuerpo)
        assert r.status_code == 422 and r.json()["error"] == "INVALID_REQUEST"
    assert filas("audit_logs") == []
