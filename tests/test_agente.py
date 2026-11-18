"""Agente asistente y base de conocimiento (spec §15: INV-04, INV-05, INV-06).

Sin red ni costo: el LLM se reemplaza por un guion (`ModeloFalso`) y los embeddings por un bolsa-de-palabras
determinista. SQLite y ChromaDB usan directorios temporales (nunca tocan `turnos.db` ni `chroma_db/`).
Lo que se prueba es lo que NO depende del modelo: que cada herramienta use la lógica real del backend.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings
from fastapi.testclient import TestClient

import agent
import ingestar_conocimiento as ing
import main

DOC = """# Políticas

## Cobertura
Aceptamos OSDE, Swiss Medical y Galeno.

## Cancelación
Se puede cancelar con 2 horas de anticipación.
"""
DOC_ECO = """# Preparaciones

## Ecografía abdominal
Concurrir con 8 horas de ayuno y vejiga llena.
"""


class EmbeddingBolsaDePalabras(EmbeddingFunction):
    """Embedding determinista de 256 dimensiones por hash de palabras (sin descargar modelos)."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        salida = []
        for texto in input:
            v = [0.0] * 256
            for w in re.findall(r"\w+", texto.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1.0
            salida.append(v)
        return salida

    @staticmethod
    def name() -> str:
        return "bolsa_de_palabras_test"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return EmbeddingBolsaDePalabras()


def uso(nombre, entrada, id_="t1"):
    return SimpleNamespace(type="tool_use", id=id_, name=nombre, input=entrada)


def respuesta(*bloques, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=list(bloques))


def texto(t):
    return respuesta(SimpleNamespace(type="text", text=t), stop="end_turn")


class ModeloFalso:
    """Reemplaza a `anthropic.Anthropic`: devuelve respuestas guionadas y registra los pedidos."""

    def __init__(self, *guion):
        self.guion, self.pedidos = list(guion), []
        self.messages = self
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kwargs):
        self.pedidos.append(kwargs)
        return self.guion.pop(0) if self.guion else respuesta(uso("consultar_turnos", {}))


def proximo_slot(delta: timedelta) -> datetime:
    t = (datetime.now(timezone.utc) + delta).replace(second=0, microsecond=0)
    return t + timedelta(minutes=(-t.minute) % 15)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "turnos_test.db")
    monkeypatch.setattr(ing, "CHROMA_PATH", tmp_path / "chroma_test")
    monkeypatch.setattr(ing, "EMBEDDING_FUNCTION", EmbeddingBolsaDePalabras())
    with TestClient(main.app) as c:
        yield c


def turnos(client):
    return client.get("/api/turnos").json()


# --------------------------------------------------------------------------
# Base de conocimiento (INV-06)
# --------------------------------------------------------------------------
def test_los_chunks_se_dividen_por_secciones_y_llevan_su_titulo():
    chunks = ing.dividir_en_chunks(DOC)
    assert len(chunks) == 2
    assert chunks[0].startswith("Cobertura") and "OSDE" in chunks[0]
    assert chunks[1].startswith("Cancelación")


def test_una_seccion_larga_se_subdivide_por_parrafos():
    largo = "# T\n## S\n" + "\n\n".join(f"Párrafo {i} " + "x" * 300 for i in range(6))
    chunks = ing.dividir_en_chunks(largo, max_chars=700)
    assert len(chunks) > 1 and all(len(c) < 1000 for c in chunks)


def test_ingesta_de_politicas_consultorio_recupera_el_fragmento_de_obras_sociales(client):
    """Indexa el documento real en una colección temporal y busca "OSDE" (INV-06)."""
    n = ing.ingestar_archivo(ing.ARCHIVO_POR_DEFECTO)
    assert n >= 5  # el documento se dividió en varios chunks por sección

    hits = ing.buscar_conocimiento("OSDE", top_k=3)
    assert hits and all(h["archivo"] == "politicas_consultorio.md" for h in hits)
    mejor = hits[0]["texto"]
    assert "OSDE" in mejor and "Swiss Medical" in mejor and "Galeno" in mejor  # chunk de "Obras sociales y prepagas"
    assert 0 < hits[0]["similitud"] <= 1


def test_cargar_conocimiento_indexa_en_caliente_y_se_puede_buscar(client):
    assert ing.buscar_conocimiento("OSDE") == []  # antes de subir nada, la base está vacía
    r = client.post("/api/conocimiento", files={"archivo": ("politicas.md", DOC.encode(), "text/markdown")})
    assert r.status_code == 200
    assert r.json() == {"archivo": "politicas.md", "chunks": 2}

    hits = ing.buscar_conocimiento("obras sociales OSDE Galeno", top_k=2)
    assert hits[0]["archivo"] == "politicas.md" and "OSDE" in hits[0]["texto"]
    assert set(hits[0]) == {"texto", "archivo", "distancia", "similitud"}
    assert hits[0]["similitud"] == pytest.approx(1 - hits[0]["distancia"], abs=1e-3)
    assert len(ing.buscar_conocimiento("obras sociales", top_k=1)) == 1


def test_documento_nuevo_queda_disponible_sin_reiniciar_y_reingestar_reemplaza(client):
    client.post("/api/conocimiento", files={"archivo": ("politicas.md", DOC.encode(), "text/markdown")})
    assert all("ayuno" not in h["texto"] for h in ing.buscar_conocimiento("ecografía ayuno", top_k=5))

    client.post("/api/conocimiento", files={"archivo": ("preparaciones.txt", DOC_ECO.encode(), "text/plain")})
    assert "ayuno" in ing.buscar_conocimiento("ecografía ayuno vejiga", top_k=1)[0]["texto"]

    r = client.post("/api/conocimiento", files={"archivo": ("politicas.md", DOC.encode(), "text/markdown")})
    assert r.json()["chunks"] == 2
    assert len(ing.buscar_conocimiento("cobertura", top_k=10)) == 3  # 2 de politicas.md (sin duplicar) + 1 de preparaciones


@pytest.mark.parametrize("nombre,contenido", [("x.pdf", b"%PDF"), ("vacio.md", b"  \n"), ("raro.md", b"\xff\xfe\x00")])
def test_cargar_conocimiento_rechaza_archivos_invalidos(client, nombre, contenido):
    r = client.post("/api/conocimiento", files={"archivo": (nombre, contenido, "application/octet-stream")})
    assert r.status_code == 422 and r.json()["error"] == "INVALID_REQUEST"


def test_buscar_en_base_vacia_devuelve_lista_vacia(client):
    assert ing.buscar_conocimiento("lo que sea") == []


# --------------------------------------------------------------------------
# Herramientas del agente = lógica real del backend (INV-04, INV-05)
# --------------------------------------------------------------------------
def test_reservar_turno_crea_el_turno_real_y_queda_auditado(client):
    inicio = proximo_slot(timedelta(days=1))
    modelo = ModeloFalso(
        respuesta(uso("reservar_turno", {"paciente": "c1", "servicio_id": "s1", "fecha_hora": iso(inicio)})),
        texto("Listo, quedó confirmado."),
    )
    out = agent.ejecutar_agente("reservame", cliente_id="c1", client=modelo)

    assert [t["herramienta"] for t in out["tools_usadas"]] == ["reservar_turno"]
    assert not out["tools_usadas"][0]["error"] and out["turnos_modificados"] is True
    assert [t["inicio"] for t in turnos(client)] == [iso(inicio)]  # el turno existe en SQLite
    # el resultado de la herramienta volvió al modelo en el pedido siguiente, en un único mensaje user
    ultimo = modelo.pedidos[-1]["messages"][-1]
    assert ultimo["role"] == "user" and ultimo["content"][0]["type"] == "tool_result"


def test_solapamiento_inv02_vuelve_como_error_y_no_crea_nada(client):
    inicio = proximo_slot(timedelta(days=1))
    client.post("/api/turnos", json={"cliente_id": "c3", "servicio_id": "s1", "inicio": iso(inicio)})
    modelo = ModeloFalso(
        respuesta(uso("reservar_turno", {"paciente": "c1", "servicio_id": "s1", "fecha_hora": iso(inicio)})),
        texto("Ese horario no está disponible."),
    )
    out = agent.ejecutar_agente("reservame", cliente_id="c1", client=modelo)

    t = out["tools_usadas"][0]
    assert t["error"] and t["resultado"]["error"] == "SLOT_UNAVAILABLE"
    assert out["turnos_modificados"] is False and len(turnos(client)) == 1
    assert modelo.pedidos[-1]["messages"][-1]["content"][0]["is_error"] is True
    with main.read_conn() as conn:  # directamente en SQLite: ninguna fila duplicada ni a medias
        assert conn.execute("SELECT COUNT(*) FROM turno").fetchone()[0] == 1
        assert conn.execute("SELECT cliente_id FROM turno").fetchone()[0] == "c3"


def test_cancelar_a_45_minutos_inv01_es_rechazado_y_el_turno_sigue_confirmado(client, monkeypatch):
    inicio = proximo_slot(timedelta(hours=5))
    turno = client.post("/api/turnos", json={"cliente_id": "c1", "servicio_id": "s1", "inicio": iso(inicio)}).json()
    reloj = inicio - timedelta(minutes=45)
    monkeypatch.setattr(main, "utcnow", lambda: reloj)

    modelo = ModeloFalso(respuesta(uso("cancelar_turno", {"turno_id": turno["id"]})), texto("No se puede cancelar."))
    out = agent.ejecutar_agente("cancelá mi turno", cliente_id="c1", client=modelo)

    assert out["tools_usadas"][0]["resultado"]["error"] == "CANCELLATION_WINDOW_EXPIRED"
    assert turnos(client)[0]["estado"] == "CONFIRMADO"


def test_cancelar_con_anticipacion_suficiente_funciona(client):
    turno = client.post("/api/turnos", json={"cliente_id": "c1", "servicio_id": "s1", "inicio": iso(proximo_slot(timedelta(hours=5)))}).json()
    out = agent.ejecutar_agente("cancelá", cliente_id="c1", client=ModeloFalso(
        respuesta(uso("cancelar_turno", {"turno_id": turno["id"]})), texto("Cancelado.")))
    assert out["turnos_modificados"] is True and turnos(client)[0]["estado"] == "CANCELADO"


def test_el_agente_no_puede_cancelar_el_turno_de_otro_paciente(client):
    turno = client.post("/api/turnos", json={"cliente_id": "c3", "servicio_id": "s1", "inicio": iso(proximo_slot(timedelta(days=1)))}).json()
    out = agent.ejecutar_agente("cancelá", cliente_id="c1", client=ModeloFalso(
        respuesta(uso("cancelar_turno", {"turno_id": turno["id"]})), texto("No encontré ese turno.")))
    assert out["tools_usadas"][0]["resultado"]["error"] == "NOT_FOUND"
    assert turnos(client)[0]["estado"] == "CONFIRMADO"


def test_no_se_puede_reservar_para_otro_paciente_ni_cancelar_sin_sesion(client):
    inicio = iso(proximo_slot(timedelta(days=1)))
    out = agent.ejecutar_agente("x", cliente_id="c1", client=ModeloFalso(
        respuesta(uso("reservar_turno", {"paciente": "c3", "servicio_id": "s1", "fecha_hora": inicio})), texto("No.")))
    assert out["tools_usadas"][0]["resultado"]["error"] == "FORBIDDEN" and turnos(client) == []
    out = agent.ejecutar_agente("x", cliente_id=None, client=ModeloFalso(
        respuesta(uso("cancelar_turno", {"turno_id": "t"})), texto("No.")))
    assert out["tools_usadas"][0]["resultado"]["error"] == "FORBIDDEN"


def test_consultar_turnos_expone_ids_solo_de_los_turnos_del_paciente(client):
    inicio = proximo_slot(timedelta(days=1))
    mio = client.post("/api/turnos", json={"cliente_id": "c1", "servicio_id": "s1", "inicio": iso(inicio)}).json()
    client.post("/api/turnos", json={"cliente_id": "c3", "servicio_id": "s3", "inicio": iso(inicio)})
    res, err = agent.ejecutar_herramienta("consultar_turnos", {}, "c1")
    assert not err and len(res["turnos_ocupados"]) == 2 and len(res["servicios"]) == 6
    ids = [t.get("id") for t in res["turnos_ocupados"]]
    assert ids.count(None) == 1 and mio["id"] in ids
    assert all("cliente_id" not in t for t in res["turnos_ocupados"])  # RBAC-04


def test_consultar_turnos_valida_el_formato_de_fecha(client):
    res, err = agent.ejecutar_herramienta("consultar_turnos", {"fecha": "mañana"}, "c1")
    assert err and res["error"] == "INVALID_REQUEST"


def test_consultar_politicas_devuelve_fragmentos_con_similitud(client):
    ing.ingestar_texto(DOC, "politicas.md")
    res, err = agent.ejecutar_herramienta("consultar_politicas", {"pregunta": "OSDE Galeno"}, None)
    assert not err and res["fragmentos"][0]["archivo"] == "politicas.md" and "similitud" in res["fragmentos"][0]


def test_consultar_politicas_sin_documentos_avisa_que_no_hay_nada(client):
    res, _ = agent.ejecutar_herramienta("consultar_politicas", {"pregunta": "ecografía"}, None)
    assert res["fragmentos"] == [] and "aviso" in res


def test_el_system_prompt_obliga_a_las_tres_reglas(client):
    s = agent.construir_system("c1")
    assert "Lucía Fernández" in s and "INV-04" in s and "INV-05" in s and "INV-06" in s


# --------------------------------------------------------------------------
# Bucle de Tool Calling
# --------------------------------------------------------------------------
def test_el_bucle_se_corta_a_las_5_iteraciones(client):
    modelo = ModeloFalso()  # siempre pide otra herramienta
    out = agent.ejecutar_agente("hola", cliente_id="c1", client=modelo)
    assert len(modelo.pedidos) == agent.MAX_ITERACIONES == 5
    assert len(out["tools_usadas"]) == 5 and "límite" in out["respuesta"]


def test_una_herramienta_desconocida_no_rompe_el_bucle(client):
    out = agent.ejecutar_agente("hola", client=ModeloFalso(respuesta(uso("borrar_todo", {})), texto("ok")))
    assert out["tools_usadas"][0]["error"] and out["respuesta"] == "ok"


def test_pedido_normal_sin_herramientas(client):
    out = agent.ejecutar_agente("hola", client=ModeloFalso(texto("¡Hola!")))
    assert out == {"respuesta": "¡Hola!", "tools_usadas": [], "turnos_modificados": False}


# --------------------------------------------------------------------------
# POST /api/chat
# --------------------------------------------------------------------------
def test_chat_sin_api_key_responde_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/chat", json={"mensaje": "hola"})
    assert r.status_code == 503 and r.json()["error"] == "AGENT_UNAVAILABLE"


def test_chat_valida_el_cuerpo(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    for cuerpo in ({}, {"mensaje": "   "}, {"mensaje": 5}):
        r = client.post("/api/chat", json=cuerpo)
        assert r.status_code == 422 and r.json()["error"] == "INVALID_REQUEST"


def test_chat_devuelve_respuesta_y_tools_usadas(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    ing.ingestar_texto(DOC, "politicas.md")
    modelo = ModeloFalso(respuesta(uso("consultar_politicas", {"pregunta": "obras sociales"})), texto("OSDE, Swiss Medical y Galeno."))
    monkeypatch.setattr(agent, "_crear_cliente", lambda: modelo)

    r = client.post("/api/chat", json={"mensaje": "¿Qué obras sociales aceptan?", "cliente_id": "c1"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["respuesta"] == "OSDE, Swiss Medical y Galeno."
    assert [t["herramienta"] for t in cuerpo["tools_usadas"]] == ["consultar_politicas"]
    assert cuerpo["turnos_modificados"] is False
