"""Backend de Turnos Pro (Fase 2) — FastAPI + SQLite.

Fuente de verdad: spec.md v0.2.1 (§4 esquema, §7 errores, §11 contrato REST) y plan.md v2.
Reglas hechas cumplir en el servidor: INV-01 (RN-01), INV-02 (RN-02), INV-03 (persistencia atómica),
RN-03, RN-04 (parcial: ver "Fuera de alcance") y RN-06.

Fase 3 (spec §15): agente asistente `POST /api/chat` (agent.py) y base de conocimiento
`POST /api/conocimiento` (ingestar_conocimiento.py, ChromaDB). Ambos reutilizan la lógica de este archivo.

Fuera de alcance en esta fase (spec §9, plan §5): horario laboral, bloqueos, auditoría, emails, login.

Organización del archivo:
    1. Configuración     constantes del spec
    2. Errores           DomainError y catálogo de la §7
    3. Tiempo            utilidades UTC
    4. Persistencia      esquema SQLite, semilla y transacciones
    5. Esquemas          modelos Pydantic de entrada y salida
    6. Reglas de dominio funciones que operan sobre la conexión de la transacción
    7. API               aplicación FastAPI y endpoints

Levantar:  uvicorn main:app --reload --port 8001      Swagger UI: http://localhost:8001/docs
Probar:    python -m pytest
"""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, AsyncIterator, Iterator, Literal, Optional

from fastapi import FastAPI, Path as RutaParam, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StringConstraints

# ----------------------------------------------------------------------------
# Configuración (constantes del spec)
# ----------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("TURNOS_DB", Path(__file__).with_name("turnos.db")))
CANCELLATION_WINDOW = timedelta(hours=2)   # RN-01
MIN_LEAD_TIME = timedelta(hours=1)         # RN-04 antelación mínima
MAX_HORIZON = timedelta(days=60)           # RN-04 horizonte máximo
SLOT_GRID_MIN = 15                         # RN-04 grilla de slots
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"           # UTC, ancho fijo: el orden de texto = orden temporal

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


# ----------------------------------------------------------------------------
# Errores de dominio (catálogo spec §7)
# ----------------------------------------------------------------------------
class DomainError(Exception):
    """Violación de una regla de negocio; se responde como `{"error": code, "detalle": detail}`."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status, self.code, self.detail = status, code, detail


def slot_unavailable(detail: str) -> DomainError:
    """409 SLOT_UNAVAILABLE (RN-02)."""
    return DomainError(409, "SLOT_UNAVAILABLE", detail)


def not_found(detail: str = "Recurso no encontrado.") -> DomainError:
    """404 NOT_FOUND. También se usa para recursos ajenos (RBAC-02)."""
    return DomainError(404, "NOT_FOUND", detail)


# ----------------------------------------------------------------------------
# Tiempo
# ----------------------------------------------------------------------------
def utcnow() -> datetime:
    """Hora actual en UTC. Único punto de lectura del reloj: los tests lo reemplazan para simular el tiempo."""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Normaliza a UTC sin microsegundos; un datetime sin zona horaria se asume UTC."""
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).replace(microsecond=0)


def fmt(dt: datetime) -> str:
    """datetime → texto UTC de ancho fijo (`TS_FORMAT`), tal como se guarda en la base."""
    return to_utc(dt).strftime(TS_FORMAT)


def parse(ts: str) -> datetime:
    """Texto UTC de la base (`TS_FORMAT`) → datetime con zona horaria."""
    return datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------------------
# Persistencia (capa 3) — esquema idéntico a spec §4.1
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS usuario (
    id               TEXT PRIMARY KEY,
    email            TEXT NOT NULL UNIQUE,
    email_verificado INTEGER NOT NULL DEFAULT 0,
    password_hash    TEXT NOT NULL,
    nombre_completo  TEXT NOT NULL,
    telefono         TEXT NOT NULL,
    rol              TEXT NOT NULL CHECK (rol IN ('CLIENTE','PROFESIONAL','ADMIN')),
    activo           INTEGER NOT NULL DEFAULT 1,
    creado_en        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS servicio (
    id                TEXT PRIMARY KEY,
    profesional_id    TEXT NOT NULL REFERENCES usuario(id),
    nombre            TEXT NOT NULL,
    descripcion       TEXT,
    duracion_min      INTEGER NOT NULL CHECK (duracion_min BETWEEN 15 AND 480),
    precio_referencia REAL NOT NULL CHECK (precio_referencia >= 0),
    activo            INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS turno (
    id                 TEXT PRIMARY KEY,
    cliente_id         TEXT NOT NULL REFERENCES usuario(id),
    profesional_id     TEXT NOT NULL REFERENCES usuario(id),
    servicio_id        TEXT NOT NULL REFERENCES servicio(id),
    inicio             TEXT NOT NULL,
    fin                TEXT NOT NULL,
    estado             TEXT NOT NULL CHECK (estado IN ('CONFIRMADO','CANCELADO','COMPLETADO','AUSENTE')),
    motivo_cancelacion TEXT,
    cancelado_por_id   TEXT REFERENCES usuario(id),
    creado_en          TEXT NOT NULL,
    actualizado_en     TEXT NOT NULL,
    CHECK (cliente_id <> profesional_id),
    CHECK (inicio < fin)
);
CREATE INDEX IF NOT EXISTS idx_turno_prof_inicio ON turno(profesional_id, inicio);
"""

# Semilla tomada de los datos mock de index.html (sin turnos: los crea la API).
SEED_USERS = [
    ("admin", "ADMIN", "Admin General", "admin@turnospro.test", "+5491100000000", 1),
    ("p1", "PROFESIONAL", "Dra. Ana Martínez", "ana@turnospro.test", "+5491100000001", 1),
    ("p2", "PROFESIONAL", "Dr. Bruno Salas", "bruno@turnospro.test", "+5491100000002", 1),
    ("p3", "PROFESIONAL", "Lic. Carla Ibáñez", "carla@turnospro.test", "+5491100000003", 1),
    ("c1", "CLIENTE", "Lucía Fernández", "lucia@mail.test", "+5491155550101", 1),
    ("c2", "CLIENTE", "Martín Gómez", "martin@mail.test", "+5491155550102", 0),
    ("c3", "CLIENTE", "Sofía Ruiz", "sofia@mail.test", "+5491155550103", 1),
]
SEED_SERVICES = [
    ("s1", "p1", "Consulta general", "Evaluación clínica y orientación.", 30, 18000),
    ("s2", "p1", "Control anual", "Chequeo completo con estudios básicos.", 60, 32000),
    ("s3", "p2", "Sesión de terapia", "Sesión individual.", 45, 25000),
    ("s4", "p2", "Evaluación inicial", "Primera entrevista y plan de trabajo.", 60, 30000),
    ("s5", "p3", "Asesoría nutricional", "Seguimiento y ajustes.", 30, 15000),
    ("s6", "p3", "Plan alimentario", "Diseño de plan personalizado.", 45, 22000),
]
NO_LOGIN_HASH = "!SIN_LOGIN_FASE_2"  # F-01 no existe todavía (spec D-06); no es un hash válido


def connect() -> sqlite3.Connection:
    """Abre una conexión nueva a `DB_PATH` (se lee en cada llamada, por eso los tests pueden cambiarla)."""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # transacciones manuales
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def write_tx() -> Iterator[sqlite3.Connection]:
    """Transacción de escritura exclusiva: verificación + escritura atómicas (INV-03, RN-02)."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def read_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Crea las tablas si no existen y carga la semilla solo si la base está vacía."""
    now = fmt(utcnow())
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM usuario").fetchone()[0] == 0:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "INSERT INTO usuario (id, rol, nombre_completo, email, telefono, email_verificado,"
                " password_hash, activo, creado_en) VALUES (?,?,?,?,?,?,?,1,?)",
                [(i, r, n, e, t, v, NO_LOGIN_HASH, now) for (i, r, n, e, t, v) in SEED_USERS],
            )
            conn.executemany(
                "INSERT INTO servicio (id, profesional_id, nombre, descripcion, duracion_min,"
                " precio_referencia, activo) VALUES (?,?,?,?,?,?,1)",
                SEED_SERVICES,
            )
            conn.execute("COMMIT")
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Esquemas de la API (Pydantic)
# ----------------------------------------------------------------------------
class Estado(str, Enum):
    """Ciclo de vida de un turno (RN-06). CANCELADO, COMPLETADO y AUSENTE son estados terminales."""

    CONFIRMADO = "CONFIRMADO"
    CANCELADO = "CANCELADO"
    COMPLETADO = "COMPLETADO"
    AUSENTE = "AUSENTE"


# Identificador de texto: se recortan los espacios y se rechaza el vacío ("" o "   " → 422 INVALID_REQUEST).
IdTexto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TurnoCreate(BaseModel):
    """Cuerpo de `POST /api/turnos`. El profesional y el `fin` los calcula el servidor."""

    cliente_id: IdTexto = Field(description="Id del cliente que reserva (rol CLIENTE, activo).", examples=["c1"])
    servicio_id: IdTexto = Field(description="Id del servicio a reservar; determina profesional y duración.", examples=["s1"])
    inicio: datetime = Field(
        description="Inicio del turno (ISO 8601; sin zona horaria se asume UTC). "
                    "Debe ser ≥ 1 h en el futuro, ≤ 60 días y múltiplo de 15 min (RN-04).",
        examples=["2026-11-10T14:30:00Z"],
    )


class CancelarIn(BaseModel):
    """Cuerpo de `POST /api/turnos/{id}/cancelar`."""

    cancelado_por_id: IdTexto = Field(description="Id del usuario que cancela (provisorio hasta tener login, D-06).", examples=["c1"])
    motivo_cancelacion: Optional[str] = Field(
        default=None,
        description="Motivo de la cancelación. Obligatorio si cancela un PROFESIONAL o ADMIN (RN-01).",
        examples=["El profesional no puede atender ese día."],
    )


class TurnoOut(BaseModel):
    """Turno tal como se guarda en la base (fechas en UTC, formato `YYYY-MM-DDTHH:MM:SSZ`)."""

    id: str
    cliente_id: str
    profesional_id: str
    servicio_id: str
    inicio: str
    fin: str
    estado: Estado
    motivo_cancelacion: Optional[str]
    cancelado_por_id: Optional[str]
    creado_en: str
    actualizado_en: str


class ErrorOut(BaseModel):
    """Cuerpo de toda respuesta de error (catálogo spec §7)."""

    error: str = Field(description="Código de error del catálogo, p. ej. `SLOT_UNAVAILABLE`.")
    detalle: str = Field(description="Explicación legible para mostrar al usuario.")


class ChatMensaje(BaseModel):
    """Un mensaje previo de la conversación (el cliente reenvía el historial en cada pedido, spec D-10)."""

    role: Literal["user", "assistant"]
    content: str


class ChatIn(BaseModel):
    """Cuerpo de `POST /api/chat`."""

    mensaje: IdTexto = Field(description="Mensaje del usuario en lenguaje natural.", examples=["¿Qué obras sociales aceptan?"])
    cliente_id: Optional[str] = Field(default=None, description="Paciente de la sesión (provisorio, D-06). El agente solo reserva y cancela para él.", examples=["c1"])
    historial: list[ChatMensaje] = Field(default_factory=list, description="Mensajes anteriores de la conversación (solo texto).")


class ToolUsada(BaseModel):
    """Auditoría de una herramienta ejecutada por el agente (INV-04)."""

    herramienta: str
    entrada: dict
    resultado: dict
    error: bool


class ChatOut(BaseModel):
    respuesta: str
    tools_usadas: list[ToolUsada]
    turnos_modificados: bool = Field(description="`true` si el agente creó o canceló un turno (el frontend refresca la tabla).")


class ConocimientoOut(BaseModel):
    archivo: str
    chunks: int


def fila_a_turno_out(row: sqlite3.Row) -> TurnoOut:
    """Convierte una fila de la tabla `turno` en el esquema de salida."""
    return TurnoOut(**{k: row[k] for k in TurnoOut.model_fields})


# ----------------------------------------------------------------------------
# Reglas de dominio (funciones sobre la conexión de la transacción)
# ----------------------------------------------------------------------------
def validar_contacto(user: sqlite3.Row) -> None:
    """RN-03: nombre, email, teléfono válidos y email verificado."""
    name = (user["nombre_completo"] or "").strip()
    if not (2 <= len(name) <= 100):
        raise DomainError(422, "INVALID_CONTACT", "El nombre completo debe tener entre 2 y 100 caracteres.")
    if not EMAIL_RE.match((user["email"] or "").strip().lower()):
        raise DomainError(422, "INVALID_CONTACT", "El email no es válido.")
    if not PHONE_E164_RE.match((user["telefono"] or "").strip()):
        raise DomainError(422, "INVALID_CONTACT", "El teléfono debe estar en formato E.164 (ej. +5491155550101).")
    if not user["email_verificado"]:
        raise DomainError(403, "EMAIL_NOT_VERIFIED", "Verificá tu email antes de reservar.")


def validar_horario(inicio: datetime, now: datetime) -> None:
    """RN-04: futuro con antelación mínima, grilla de 15 min y horizonte máximo."""
    if inicio < now + MIN_LEAD_TIME:
        raise DomainError(422, "INVALID_TIME_RANGE", "El turno debe comenzar con al menos 1 hora de antelación.")
    if inicio > now + MAX_HORIZON:
        raise DomainError(422, "INVALID_TIME_RANGE", "No se puede reservar con más de 60 días de anticipación.")
    if inicio.second != 0 or inicio.minute % SLOT_GRID_MIN != 0:
        raise DomainError(422, "INVALID_TIME_RANGE", f"El inicio debe estar alineado a la grilla de {SLOT_GRID_MIN} minutos.")


def verificar_sin_solapamiento(conn: sqlite3.Connection, column: str, owner_id: str, inicio: str, fin: str) -> None:
    """INV-02: sin solapamiento de [inicio, fin) entre turnos CONFIRMADO (contiguos son válidos)."""
    row = conn.execute(
        f"SELECT 1 FROM turno WHERE {column} = ? AND estado = 'CONFIRMADO' AND inicio < ? AND ? < fin LIMIT 1",
        (owner_id, fin, inicio),
    ).fetchone()
    if row:
        who = "El profesional" if column == "profesional_id" else "El cliente"
        raise slot_unavailable(f"{who} ya tiene un turno confirmado que se solapa con ese horario.")


def registrar_turno(conn: sqlite3.Connection, data: TurnoCreate, now: datetime) -> sqlite3.Row:
    """Valida y crea un turno CONFIRMADO. Debe llamarse dentro de `write_tx` (INV-03).

    Orden de validación: existencia (404) → contacto (RN-03) → horario (RN-04) → solapamiento (INV-02).
    """
    cliente = conn.execute("SELECT * FROM usuario WHERE id = ? AND rol = 'CLIENTE' AND activo = 1", (data.cliente_id,)).fetchone()
    servicio = conn.execute("SELECT * FROM servicio WHERE id = ? AND activo = 1", (data.servicio_id,)).fetchone()
    if cliente is None:
        raise not_found("Cliente inexistente.")
    if servicio is None:
        raise not_found("Servicio inexistente o inactivo.")
    validar_contacto(cliente)
    inicio_dt = to_utc(data.inicio)
    validar_horario(inicio_dt, now)
    inicio, fin = fmt(inicio_dt), fmt(inicio_dt + timedelta(minutes=servicio["duracion_min"]))
    verificar_sin_solapamiento(conn, "profesional_id", servicio["profesional_id"], inicio, fin)
    verificar_sin_solapamiento(conn, "cliente_id", cliente["id"], inicio, fin)
    turno_id, ts = str(uuid.uuid4()), fmt(now)
    conn.execute(
        "INSERT INTO turno (id, cliente_id, profesional_id, servicio_id, inicio, fin, estado, creado_en, actualizado_en)"
        " VALUES (?,?,?,?,?,?,'CONFIRMADO',?,?)",
        (turno_id, cliente["id"], servicio["profesional_id"], servicio["id"], inicio, fin, ts, ts),
    )
    return conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)).fetchone()


def registrar_cancelacion(conn: sqlite3.Connection, turno_id: str, data: CancelarIn, now: datetime) -> sqlite3.Row:
    """Cancela un turno CONFIRMADO. Debe llamarse dentro de `write_tx` (INV-03).

    Orden de validación: existencia y pertenencia (404) → estado terminal (409, RN-06)
    → ventana de 2 h solo para CLIENTE (409, INV-01) o motivo obligatorio para PROFESIONAL/ADMIN (422).
    """
    turno = conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)).fetchone()
    actor = conn.execute("SELECT * FROM usuario WHERE id = ? AND activo = 1", (data.cancelado_por_id,)).fetchone()
    if turno is None or actor is None:
        raise not_found("Turno inexistente.")
    # RBAC-02: un recurso ajeno responde 404, no 403.
    if actor["rol"] == "CLIENTE" and turno["cliente_id"] != actor["id"]:
        raise not_found("Turno inexistente.")
    if actor["rol"] == "PROFESIONAL" and turno["profesional_id"] != actor["id"]:
        raise not_found("Turno inexistente.")
    if turno["estado"] != "CONFIRMADO":  # RN-06: estados terminales
        raise DomainError(409, "INVALID_STATE_TRANSITION", f"El turno está {turno['estado']} y no puede cancelarse.")
    motivo = (data.motivo_cancelacion or "").strip() or None
    if actor["rol"] == "CLIENTE":
        # INV-01: el cliente no cancela con menos de 2 h (exactamente 2 h sí se permite).
        if parse(turno["inicio"]) - now < CANCELLATION_WINDOW:
            raise DomainError(409, "CANCELLATION_WINDOW_EXPIRED",
                              "Solo se puede cancelar hasta 2 horas antes del inicio del turno.")
    elif motivo is None:
        raise DomainError(422, "INVALID_REQUEST", "El motivo de cancelación es obligatorio para Profesional/Administrador.")
    conn.execute(
        "UPDATE turno SET estado = 'CANCELADO', motivo_cancelacion = ?, cancelado_por_id = ?, actualizado_en = ? WHERE id = ?",
        (motivo, actor["id"], fmt(now), turno_id),
    )
    return conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)).fetchone()


# ----------------------------------------------------------------------------
# Aplicación FastAPI (capa 2)
# ----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Al iniciar el servidor crea las tablas y la semilla (ver `init_db`)."""
    init_db()
    yield


DESCRIPCION_API = """
API REST de **Turnos Pro**: reserva y cancelación de turnos con profesionales.

Reglas que hace cumplir el servidor (ver `spec.md`):

* **INV-01** — un cliente no puede cancelar con menos de 2 horas de anticipación.
* **INV-02** — no se solapan turnos `CONFIRMADO` del mismo profesional ni del mismo cliente.
* **INV-03** — los datos se guardan en SQLite y la verificación y la escritura son atómicas.

Todos los errores responden `{"error": CODIGO, "detalle": texto}` (catálogo spec §7).
"""

app = FastAPI(
    title="Turnos Pro API",
    version="0.2.1",
    description=DESCRIPCION_API,
    openapi_tags=[{"name": "Turnos", "description": "Consulta, reserva y cancelación de turnos."}],
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    """Traduce una `DomainError` a su respuesta HTTP según el catálogo de la §7."""
    return JSONResponse(status_code=exc.status, content={"error": exc.code, "detalle": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Errores de validación de Pydantic (campos faltantes, tipos o textos vacíos) → 422 INVALID_REQUEST."""
    detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=422, content={"error": "INVALID_REQUEST", "detalle": detail})


@app.get("/", include_in_schema=False)
def servir_frontend() -> FileResponse:
    """Sirve la interfaz web (`prototipo-turnos.html`), que consume esta misma API."""
    return FileResponse(Path(__file__).parent / "prototipo-turnos.html", media_type="text/html")


@app.get(
    "/api/turnos",
    response_model=list[TurnoOut],
    tags=["Turnos"],
    summary="Listar turnos",
    responses={422: {"model": ErrorOut, "description": "`INVALID_REQUEST`: filtro con formato o valor inválido."}},
)
def listar_turnos(
    cliente_id: Optional[str] = Query(default=None, description="Solo los turnos de este cliente."),
    profesional_id: Optional[str] = Query(default=None, description="Solo los turnos de este profesional."),
    estado: Optional[Estado] = Query(default=None, description="Solo los turnos en este estado."),
) -> list[TurnoOut]:
    """Devuelve los turnos ordenados por `inicio`. Los filtros son opcionales y se combinan con AND.

    Los datos se leen siempre de la base (INV-03), nunca de una caché en memoria.
    """
    where, params = [], []
    for column, value in (("cliente_id", cliente_id), ("profesional_id", profesional_id)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    if estado is not None:
        where.append("estado = ?")
        params.append(estado.value)
    sql = "SELECT * FROM turno" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY inicio"
    with read_conn() as conn:
        return [fila_a_turno_out(r) for r in conn.execute(sql, params).fetchall()]


@app.post(
    "/api/turnos",
    response_model=TurnoOut,
    status_code=201,
    tags=["Turnos"],
    summary="Crear una reserva",
    responses={
        403: {"model": ErrorOut, "description": "`EMAIL_NOT_VERIFIED`: el cliente no verificó su email (RN-03)."},
        404: {"model": ErrorOut, "description": "`NOT_FOUND`: cliente o servicio inexistente o inactivo."},
        409: {"model": ErrorOut, "description": "`SLOT_UNAVAILABLE`: se solapa con otro turno confirmado (INV-02)."},
        422: {"model": ErrorOut, "description": "`INVALID_REQUEST` (cuerpo mal formado o textos vacíos), "
                                                "`INVALID_TIME_RANGE` (RN-04) o `INVALID_CONTACT` (RN-03)."},
    },
)
def crear_turno(data: TurnoCreate) -> TurnoOut:
    """Crea un turno `CONFIRMADO` para el cliente y servicio indicados.

    El profesional y el `fin` se calculan a partir del servicio. La validación y la inserción
    ocurren en una única transacción exclusiva (INV-03), por lo que dos pedidos simultáneos
    por el mismo horario no pueden confirmarse ambos.
    """
    with write_tx() as conn:
        return fila_a_turno_out(registrar_turno(conn, data, utcnow()))


@app.post(
    "/api/turnos/{turno_id}/cancelar",
    response_model=TurnoOut,
    tags=["Turnos"],
    summary="Cancelar un turno",
    responses={
        404: {"model": ErrorOut, "description": "`NOT_FOUND`: el turno no existe o es de otro usuario (RBAC-02)."},
        409: {"model": ErrorOut, "description": "`CANCELLATION_WINDOW_EXPIRED` (faltan menos de 2 h, INV-01) "
                                                "o `INVALID_STATE_TRANSITION` (el turno ya no está `CONFIRMADO`, RN-06)."},
        422: {"model": ErrorOut, "description": "`INVALID_REQUEST`: cuerpo mal formado o motivo ausente "
                                                "cuando cancela un PROFESIONAL/ADMIN."},
    },
)
def cancelar_turno(data: CancelarIn, turno_id: str = RutaParam(description="Id del turno a cancelar.")) -> TurnoOut:
    """Pasa el turno a `CANCELADO`. El turno nunca se elimina físicamente (RN-06).

    Un `CLIENTE` solo puede cancelar sus propios turnos y con al menos 2 horas de anticipación
    (exactamente 2 h se permite). `PROFESIONAL` y `ADMIN` pueden cancelar fuera de esa ventana
    siempre que indiquen un motivo.
    """
    with write_tx() as conn:
        return fila_a_turno_out(registrar_cancelacion(conn, turno_id, data, utcnow()))


# ----------------------------------------------------------------------------
# Fase 3 (spec §15): agente asistente y base de conocimiento
# ----------------------------------------------------------------------------
@app.post(
    "/api/chat",
    response_model=ChatOut,
    tags=["Agente"],
    summary="Chatear con el asistente de turnos",
    responses={
        422: {"model": ErrorOut, "description": "`INVALID_REQUEST`: cuerpo mal formado o mensaje vacío."},
        503: {"model": ErrorOut, "description": "`AGENT_UNAVAILABLE`: falta ANTHROPIC_API_KEY o el servicio del modelo no responde."},
    },
)
def chat(data: ChatIn) -> ChatOut:
    """El agente responde con herramientas reales: consulta y reserva/cancela turnos en SQLite (INV-04) a través
    de las mismas reglas de la API REST (INV-05) y responde sobre políticas solo con fragmentos de ChromaDB (INV-06).
    `tools_usadas` lista las herramientas ejecutadas para poder auditarlas."""
    import anthropic

    import agent  # import diferido: carga .env y evita un import circular con este módulo

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise DomainError(503, "AGENT_UNAVAILABLE", "El asistente no está configurado: falta ANTHROPIC_API_KEY en el archivo .env.")
    try:
        salida = agent.ejecutar_agente(data.mensaje, data.cliente_id, [m.model_dump() for m in data.historial])
    except anthropic.APIError as exc:
        raise DomainError(503, "AGENT_UNAVAILABLE", f"El servicio del asistente no respondió ({type(exc).__name__}).")
    return ChatOut(**salida)


@app.post(
    "/api/conocimiento",
    response_model=ConocimientoOut,
    tags=["Agente"],
    summary="Cargar un documento a la base de conocimiento",
    responses={422: {"model": ErrorOut, "description": "`INVALID_REQUEST`: archivo ausente, vacío, no UTF-8 o con extensión distinta de `.md`/`.txt`."}},
)
def cargar_conocimiento(archivo: UploadFile) -> ConocimientoOut:
    """Indexa en caliente un `.md` o `.txt` en ChromaDB (sin reiniciar el servidor). Si ya existía un archivo con
    el mismo nombre, reemplaza sus fragmentos. Queda disponible para el agente en el pedido siguiente (INV-06)."""
    from ingestar_conocimiento import ingestar_texto

    nombre = Path(archivo.filename or "").name
    if Path(nombre).suffix.lower() not in (".md", ".txt"):
        raise DomainError(422, "INVALID_REQUEST", "Solo se aceptan archivos .md o .txt.")
    try:
        texto = archivo.file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DomainError(422, "INVALID_REQUEST", "El archivo debe estar codificado en UTF-8.")
    chunks = ingestar_texto(texto, nombre) if texto.strip() else 0
    if chunks == 0:
        raise DomainError(422, "INVALID_REQUEST", "El archivo está vacío.")
    return ConocimientoOut(archivo=nombre, chunks=chunks)
