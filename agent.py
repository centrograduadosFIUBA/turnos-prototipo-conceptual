"""Agente asistente de turnos (spec §15: INV-04, INV-05, INV-06) — SDK de Anthropic con Tool Calling.

El agente NO tiene lógica de negocio propia: sus 4 herramientas llaman a las funciones reales del backend
(`main.registrar_turno`, `main.registrar_cancelacion`, SQLite) y a la base vectorial (`buscar_conocimiento`).
 - INV-04: solo afirma lo que devolvió una herramienta ejecutada en el mismo intercambio.
 - INV-05: toda reserva/cancelación pasa por INV-01 e INV-02; los 409 vuelven al modelo como resultado de
           herramienta con error para que los explique con amabilidad.
 - INV-06: consultas sobre servicios/coberturas/preparaciones solo con fragmentos de ChromaDB; si no hay, abstenerse.
 - INV-07: cada reserva/cancelación confirmada se avisa con `notificar(evento, turno)`.
 - INV-08: máximo 5 iteraciones y corte ante una llamada idéntica consecutiva.
 - INV-09: cada ejecución deja exactamente una fila en `audit_logs`.

Uso:  from agent import ejecutar_agente
      ejecutar_agente("¿Qué obras sociales aceptan?", cliente_id="c1")  ->  {"respuesta", "tools_usadas", "turnos_modificados"}
Requiere ANTHROPIC_API_KEY (en `.env` o en el entorno). Modelo: ANTHROPIC_MODEL (default claude-opus-5-5).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

import main
from ingestar_conocimiento import buscar_conocimiento

load_dotenv()

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_ITERACIONES = 5          # tope de llamadas al modelo por pedido de chat
MAX_TOKENS = 4096
TOP_K = 4                    # fragmentos recuperados por consulta de políticas
TZ_OPERACION = timezone(timedelta(hours=-3))  # zona de operación (Argentina, sin horario de verano)
# Reintento automático del lado del servidor si el modelo rechaza la solicitud por política (no afecta las reglas INV).
USAR_FALLBACKS = os.environ.get("ANTHROPIC_FALLBACKS", "1") != "0"

# ----------------------------------------------------------------------------
# Definición de herramientas (lo que ve el modelo)
# ----------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "consultar_politicas",
        "description": (
            "Busca en la base de conocimiento del consultorio (documentos cargados) los fragmentos más "
            "relevantes para una pregunta sobre especialidades, horarios de atención, obras sociales, "
            "prepagas, atención particular, políticas de cancelación o preparación de estudios. "
            "Devuelve fragmentos con su archivo de origen y similitud. Es la ÚNICA fuente permitida para "
            "responder ese tipo de consultas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"pregunta": {"type": "string", "description": "La consulta del usuario, en lenguaje natural."}},
            "required": ["pregunta"],
        },
    },
    {
        "name": "consultar_turnos",
        "description": (
            "Consulta en la base de datos real los turnos CONFIRMADOS (horarios ocupados) y el catálogo de "
            "servicios con su profesional y duración. Úsala SIEMPRE antes de informar disponibilidad: un "
            "horario es libre solo si no se solapa con un turno ocupado del mismo profesional. Los turnos "
            "del paciente actual incluyen su `id` (necesario para cancelar). Sin `fecha`, devuelve los "
            "próximos turnos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"fecha": {"type": "string", "description": "Día a consultar, formato YYYY-MM-DD (hora local de Argentina). Opcional."}},
        },
    },
    {
        "name": "reservar_turno",
        "description": (
            "Crea un turno CONFIRMADO en la base de datos. El servidor valida las reglas del negocio "
            "(no solapamiento, antelación mínima de 1 hora, grilla de 15 minutos, máximo 60 días). "
            "Solo confirmale el turno al usuario si esta herramienta devuelve el turno creado. "
            "Pedí la confirmación explícita del usuario (servicio, día y hora) antes de llamarla."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paciente": {"type": "string", "description": "Id (ej. c1) o nombre completo del paciente. Si hay un paciente actual en la conversación, usá su id."},
                "servicio_id": {"type": "string", "description": "Id del servicio (ej. s1), obtenido de consultar_turnos."},
                "fecha_hora": {"type": "string", "description": "Inicio del turno en ISO 8601 con zona horaria, ej. 2026-11-20T10:30:00-03:00."},
            },
            "required": ["paciente", "servicio_id", "fecha_hora"],
        },
    },
    {
        "name": "cancelar_turno",
        "description": (
            "Cancela un turno del paciente actual. El servidor aplica la regla de cancelación mínima de "
            "2 horas de anticipación. Solo confirmale la cancelación al usuario si esta herramienta "
            "devuelve el turno en estado CANCELADO. Pedí confirmación explícita antes de llamarla."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"turno_id": {"type": "string", "description": "Id del turno, obtenido de consultar_turnos."}},
            "required": ["turno_id"],
        },
    },
]

# Herramientas que modifican turnos: el frontend refresca la tabla cuando alguna se ejecutó sin error.
HERRAMIENTAS_DE_ESCRITURA = {"reservar_turno", "cancelar_turno"}
EVENTOS_WEBHOOK = {"reservar_turno": "turno.creado", "cancelar_turno": "turno.cancelado"}  # INV-07

# Respuesta fija del circuit breaker (INV-08): la genera el servidor, sin llamar de nuevo al modelo.
MENSAJE_CIRCUIT_BREAKER = (
    "No pude completar la acción: me detuve para no repetir pasos sin avanzar. No des por hecha ninguna "
    "operación que no figure en la tabla de turnos y revisala antes de volver a intentar."
)


def construir_system(cliente_id: Optional[str]) -> str:
    """Prompt del sistema. Incluye la hora actual (el modelo no la conoce) y el paciente de la sesión."""
    ahora = main.utcnow()
    local = ahora.astimezone(TZ_OPERACION)
    paciente = "No hay un paciente identificado: pedí su nombre para reservar. No podés cancelar sin paciente identificado."
    if cliente_id:
        with main.read_conn() as conn:
            fila = conn.execute("SELECT id, nombre_completo FROM usuario WHERE id = ? AND rol = 'CLIENTE'", (cliente_id,)).fetchone()
        if fila:
            paciente = f"Paciente actual: {fila['nombre_completo']} (id {fila['id']}). Reservás y cancelás solo para esta persona."
    return f"""Sos el asistente virtual de turnos del Centro Médico Turnos Pro. Hablás en español rioplatense, con tono amable y breve.

Fecha y hora actuales: {local.strftime('%A %d/%m/%Y %H:%M')} (hora de Argentina, UTC-3) = {ahora.strftime('%Y-%m-%dT%H:%M:%SZ')} UTC.
{paciente}

Reglas obligatorias:
1. Herramientas primero (INV-04). Nunca confirmes un turno, una cancelación ni informes disponibilidad sin haber ejecutado antes la herramienta correspondiente en esta conversación. Para saber qué horarios están libres, llamá a consultar_turnos y descartá los horarios que se solapen con turnos ocupados del mismo profesional. Si una herramienta falla, decí que la operación NO se realizó.
2. Respetá las reglas del sistema (INV-05). No intentes eludirlas ni reintentar para forzar una operación. Si una herramienta devuelve un error de negocio (horario ocupado, cancelación con menos de 2 horas de anticipación, turno ya cancelado, fecha inválida, etc.), explicáselo al usuario con claridad y amabilidad, sin mostrar códigos técnicos, y ofrecé alternativas posibles (otro horario libre) sin ejecutarlas hasta que el usuario lo pida.
3. Solo documentos (INV-06). Toda consulta sobre servicios, especialidades, horarios de atención, coberturas, obras sociales o preparaciones de estudios debe responderse únicamente con fragmentos devueltos por consultar_politicas. Si los fragmentos no contienen la respuesta, decí explícitamente que no tenés esa información en los documentos cargados y sugerí consultar con recepción. No completes con conocimiento propio ni inventes datos, aunque la respuesta te parezca obvia.
4. Antes de reservar o cancelar, confirmá con el usuario los datos (servicio, día, hora) y esperá su acuerdo. Interpretá los horarios que da el usuario como hora de Argentina y enviá fecha_hora con offset -03:00.
5. No des consejos médicos ni diagnósticos."""


# ----------------------------------------------------------------------------
# Implementación de las herramientas (lógica real, sin reglas propias)
# ----------------------------------------------------------------------------
def _hora_local(ts: str) -> str:
    return main.parse(ts).astimezone(TZ_OPERACION).strftime("%Y-%m-%d %H:%M")


def _error(code: str, detalle: str) -> dict:
    return {"error": code, "detalle": detalle}


def tool_consultar_politicas(pregunta: str, **_: Any) -> dict:
    fragmentos = buscar_conocimiento(pregunta, top_k=TOP_K)
    if not fragmentos:
        return {"fragmentos": [], "aviso": "La base de conocimiento no devolvió ningún documento."}
    return {"fragmentos": fragmentos}


def tool_consultar_turnos(fecha: Optional[str] = None, cliente_id: Optional[str] = None, **_: Any) -> dict:
    where, params = ["t.estado = 'CONFIRMADO'"], []
    if fecha:
        try:
            dia = datetime.strptime(fecha.strip(), "%Y-%m-%d").replace(tzinfo=TZ_OPERACION)
        except ValueError:
            return _error("INVALID_REQUEST", "La fecha debe tener formato YYYY-MM-DD.")
        where += ["t.inicio >= ?", "t.inicio < ?"]
        params += [main.fmt(dia), main.fmt(dia + timedelta(days=1))]
    else:
        where.append("t.fin > ?")
        params.append(main.fmt(main.utcnow()))
    with main.read_conn() as conn:
        turnos = conn.execute(
            "SELECT t.*, s.nombre AS servicio, u.nombre_completo AS profesional FROM turno t"
            " JOIN servicio s ON s.id = t.servicio_id JOIN usuario u ON u.id = t.profesional_id"
            f" WHERE {' AND '.join(where)} ORDER BY t.inicio LIMIT 60",
            params,
        ).fetchall()
        servicios = conn.execute(
            "SELECT s.id, s.nombre, s.descripcion, s.duracion_min, s.precio_referencia, u.nombre_completo AS profesional,"
            " s.profesional_id FROM servicio s JOIN usuario u ON u.id = s.profesional_id WHERE s.activo = 1 ORDER BY s.id"
        ).fetchall()
    salida = []
    for t in turnos:
        propio = bool(cliente_id) and t["cliente_id"] == cliente_id
        item = {
            "profesional_id": t["profesional_id"], "profesional": t["profesional"], "servicio": t["servicio"],
            "inicio_local": _hora_local(t["inicio"]), "fin_local": _hora_local(t["fin"]),
            "inicio_utc": t["inicio"], "fin_utc": t["fin"], "es_del_paciente": propio,
        }
        if propio:  # RBAC-04: el id (y por lo tanto la posibilidad de operar) solo se expone para turnos propios
            item["id"] = t["id"]
        salida.append(item)
    return {
        "zona_horaria": "America/Argentina/Buenos_Aires (UTC-3)",
        "turnos_ocupados": salida,
        "servicios": [dict(s) for s in servicios],
        "nota": "Los horarios de atención de cada especialidad están en los documentos (consultar_politicas).",
    }


def tool_reservar_turno(paciente: str, servicio_id: str, fecha_hora: str, cliente_id: Optional[str] = None, **_: Any) -> dict:
    with main.read_conn() as conn:
        if cliente_id:  # sesión identificada: solo puede reservar para sí mismo
            fila = conn.execute("SELECT id, nombre_completo FROM usuario WHERE id = ?", (cliente_id,)).fetchone()
            pedido = paciente.strip().lower()
            if fila is None or pedido not in (fila["id"].lower(), fila["nombre_completo"].lower()):
                return _error("FORBIDDEN", "Solo se puede reservar un turno para el paciente de la sesión actual.")
            destino = fila["id"]
        else:
            fila = conn.execute(
                "SELECT id FROM usuario WHERE rol = 'CLIENTE' AND (LOWER(id) = ? OR LOWER(nombre_completo) = ?)",
                (paciente.strip().lower(),) * 2,
            ).fetchone()
            if fila is None:
                return _error("NOT_FOUND", "No se encontró un paciente con ese nombre o id.")
            destino = fila["id"]
    try:
        data = main.TurnoCreate(cliente_id=destino, servicio_id=servicio_id, inicio=fecha_hora)
    except ValidationError:
        return _error("INVALID_REQUEST", "Los datos del turno no son válidos (revisá servicio y formato de fecha ISO 8601).")
    with main.write_tx() as conn:  # INV-02, RN-03, RN-04 y INV-03: la lógica y la transacción son las de la API REST
        turno = main.fila_a_turno_out(main.registrar_turno(conn, data, main.utcnow()))
    return {"turno": turno.model_dump(mode="json"), "inicio_local": _hora_local(turno.inicio), "fin_local": _hora_local(turno.fin)}


def tool_cancelar_turno(turno_id: str, cliente_id: Optional[str] = None, **_: Any) -> dict:
    if not cliente_id:
        return _error("FORBIDDEN", "No hay un paciente identificado en la sesión; no se puede cancelar.")
    data = main.CancelarIn(cancelado_por_id=cliente_id, motivo_cancelacion=None)  # actor siempre CLIENTE: aplica INV-01
    with main.write_tx() as conn:
        turno = main.fila_a_turno_out(main.registrar_cancelacion(conn, turno_id.strip(), data, main.utcnow()))
    return {"turno": turno.model_dump(mode="json")}


IMPLEMENTACIONES = {
    "consultar_politicas": tool_consultar_politicas,
    "consultar_turnos": tool_consultar_turnos,
    "reservar_turno": tool_reservar_turno,
    "cancelar_turno": tool_cancelar_turno,
}


def ejecutar_herramienta(nombre: str, entrada: dict, cliente_id: Optional[str]) -> tuple[dict, bool]:
    """Ejecuta una herramienta y devuelve (resultado, es_error). Los errores de dominio no abortan el bucle:
    vuelven al modelo como resultado con error para que los explique (INV-05)."""
    impl = IMPLEMENTACIONES.get(nombre)
    if impl is None:
        return _error("TOOL_DESCONOCIDA", f"No existe la herramienta {nombre}."), True
    try:
        resultado = impl(**entrada, cliente_id=cliente_id)
    except main.DomainError as exc:
        return _error(exc.code, exc.detail), True
    except TypeError:
        return _error("INVALID_REQUEST", "Argumentos inválidos para la herramienta."), True
    return resultado, "error" in resultado


# ----------------------------------------------------------------------------
# Bucle de Tool Calling
# ----------------------------------------------------------------------------
def _crear_cliente() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # lee ANTHROPIC_API_KEY del entorno (cargado desde .env por dotenv)


def _llamar_modelo(client: anthropic.Anthropic, system: str, messages: list[dict]):
    kwargs: dict[str, Any] = dict(model=MODEL, max_tokens=MAX_TOKENS, system=system, tools=TOOLS, messages=messages)
    global USAR_FALLBACKS
    if USAR_FALLBACKS:
        try:
            return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        except TypeError as exc:  # SDK de `anthropic` viejo, sin el parámetro `fallbacks`: seguir sin reintento automático
            if "fallbacks" not in str(exc):
                raise
            USAR_FALLBACKS = False
    return client.messages.create(**kwargs)


def _texto(content) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


def ejecutar_agente(
    mensaje: str,
    cliente_id: Optional[str] = None,
    historial: Optional[list[dict]] = None,
    client: Optional[anthropic.Anthropic] = None,
    origen: str = "chat_web",
    notificar: Optional[Callable[[str, dict], None]] = None,
) -> dict:
    """Responde a `mensaje` ejecutando herramientas reales. Devuelve `{"respuesta", "tools_usadas", "turnos_modificados"}`.

    `tools_usadas` lista cada herramienta ejecutada (nombre, entrada, resultado, error) para auditarla.
    Máximo `MAX_ITERACIONES` llamadas al modelo por pedido; corta antes si se repite una llamada (INV-08).
    `origen` (`chat_web` | `webhook_externo`) se registra en `audit_logs` (INV-09), también si hay una excepción.
    `notificar(evento, turno)` se invoca tras cada reserva o cancelación ya confirmada en la base (INV-07).
    """
    inicio, reloj = main.utcnow(), time.monotonic()
    tools_usadas: list[dict] = []
    invocadas: list[str] = []
    pasos, estado = 0, "error"  # queda en "error" si una excepción interrumpe la ejecución
    anterior: Optional[tuple[str, str]] = None  # (herramienta, argumentos) de la última llamada
    try:
        client = client or _crear_cliente()
        system = construir_system(cliente_id)
        messages: list[dict] = [{"role": m["role"], "content": m["content"]} for m in (historial or [])]
        messages.append({"role": "user", "content": mensaje})

        for _ in range(MAX_ITERACIONES):
            pasos += 1
            resp = _llamar_modelo(client, system, messages)
            if resp.stop_reason == "refusal":
                respuesta = "No puedo ayudarte con esa solicitud. Si querés, consultame por turnos o por las políticas del consultorio."
                estado = "ok"
                break
            if resp.stop_reason != "tool_use":
                respuesta, estado = _texto(resp.content) or "No pude generar una respuesta.", "ok"
                break
            messages.append({"role": "assistant", "content": resp.content})  # tal cual: incluye los bloques de razonamiento
            resultados, repetida = [], False
            for bloque in resp.content:
                if getattr(bloque, "type", None) != "tool_use":
                    continue
                entrada = dict(bloque.input or {})
                firma = (bloque.name, json.dumps(entrada, sort_keys=True, ensure_ascii=False))
                if firma == anterior:  # INV-08: la llamada repetida no se ejecuta
                    repetida = True
                    break
                anterior = firma
                invocadas.append(bloque.name)
                salida, es_error = ejecutar_herramienta(bloque.name, entrada, cliente_id)
                tools_usadas.append({"herramienta": bloque.name, "entrada": entrada, "resultado": salida, "error": es_error})
                if notificar and not es_error and bloque.name in EVENTOS_WEBHOOK:
                    notificar(EVENTOS_WEBHOOK[bloque.name], salida["turno"])
                resultados.append({
                    "type": "tool_result", "tool_use_id": bloque.id, "is_error": es_error,
                    "content": json.dumps(salida, ensure_ascii=False),
                })
            if repetida:
                respuesta, estado = MENSAJE_CIRCUIT_BREAKER, "circuit_breaker"
                break
            messages.append({"role": "user", "content": resultados})  # todos los tool_result en un único mensaje
        else:
            respuesta, estado = MENSAJE_CIRCUIT_BREAKER, "circuit_breaker"
    finally:
        main.registrar_auditoria(
            inicio=inicio, origen=origen, prompt=mensaje, herramientas=invocadas, pasos=pasos,
            latencia_ms=round((time.monotonic() - reloj) * 1000), estado=estado,
        )

    modificados = any(t["herramienta"] in HERRAMIENTAS_DE_ESCRITURA and not t["error"] for t in tools_usadas)
    return {"respuesta": respuesta, "tools_usadas": tools_usadas, "turnos_modificados": modificados}
