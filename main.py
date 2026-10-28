"""Backend de Turnos Pro (Fase 2) — FastAPI + SQLite.

Fuente de verdad: spec.md v0.2.1 (§4 esquema, §7 errores, §11 contrato REST) y plan.md v2.
Reglas hechas cumplir en el servidor: INV-01 (RN-01), INV-02 (RN-02), INV-03 (persistencia atómica),
RN-03, RN-04 (parcial: ver "Fuera de alcance") y RN-06.

Fuera de alcance en esta fase (spec §9, plan §5): horario laboral, bloqueos, auditoría, emails, login.

Levantar:  uvicorn main:app --reload --port 8000      Swagger UI: http://localhost:8000/docs
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
from typing import AsyncIterator, Iterator, Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status, self.code, self.detail = status, code, detail


def slot_unavailable(detail: str) -> DomainError:
    return DomainError(409, "SLOT_UNAVAILABLE", detail)


def not_found(detail: str = "Recurso no encontrado.") -> DomainError:
    return DomainError(404, "NOT_FOUND", detail)


# ----------------------------------------------------------------------------
# Tiempo
# ----------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).replace(microsecond=0)


def fmt(dt: datetime) -> str:
    return to_utc(dt).strftime(TS_FORMAT)


def parse(ts: str) -> datetime:
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
    CONFIRMADO = "CONFIRMADO"
    CANCELADO = "CANCELADO"
    COMPLETADO = "COMPLETADO"
    AUSENTE = "AUSENTE"


class TurnoCreate(BaseModel):
    cliente_id: str
    servicio_id: str
    inicio: datetime


class CancelarIn(BaseModel):
    cancelado_por_id: str
    motivo_cancelacion: Optional[str] = None


class TurnoOut(BaseModel):
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


def turno_out(row: sqlite3.Row) -> TurnoOut:
    return TurnoOut(**{k: row[k] for k in TurnoOut.model_fields})


# ----------------------------------------------------------------------------
# Reglas de dominio (funciones sobre la conexión de la transacción)
# ----------------------------------------------------------------------------
def validate_contact(user: sqlite3.Row) -> None:
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


def validate_time(inicio: datetime, now: datetime) -> None:
    """RN-04: futuro con antelación mínima, grilla de 15 min y horizonte máximo."""
    if inicio < now + MIN_LEAD_TIME:
        raise DomainError(422, "INVALID_TIME_RANGE", "El turno debe comenzar con al menos 1 hora de antelación.")
    if inicio > now + MAX_HORIZON:
        raise DomainError(422, "INVALID_TIME_RANGE", "No se puede reservar con más de 60 días de anticipación.")
    if inicio.second != 0 or inicio.minute % SLOT_GRID_MIN != 0:
        raise DomainError(422, "INVALID_TIME_RANGE", f"El inicio debe estar alineado a la grilla de {SLOT_GRID_MIN} minutos.")


def assert_no_overlap(conn: sqlite3.Connection, column: str, owner_id: str, inicio: str, fin: str) -> None:
    """INV-02: sin solapamiento de [inicio, fin) entre turnos CONFIRMADO (contiguos son válidos)."""
    row = conn.execute(
        f"SELECT 1 FROM turno WHERE {column} = ? AND estado = 'CONFIRMADO' AND inicio < ? AND ? < fin LIMIT 1",
        (owner_id, fin, inicio),
    ).fetchone()
    if row:
        who = "El profesional" if column == "profesional_id" else "El cliente"
        raise slot_unavailable(f"{who} ya tiene un turno confirmado que se solapa con ese horario.")


def create_turno(conn: sqlite3.Connection, data: TurnoCreate, now: datetime) -> sqlite3.Row:
    cliente = conn.execute("SELECT * FROM usuario WHERE id = ? AND rol = 'CLIENTE' AND activo = 1", (data.cliente_id,)).fetchone()
    servicio = conn.execute("SELECT * FROM servicio WHERE id = ? AND activo = 1", (data.servicio_id,)).fetchone()
    if cliente is None:
        raise not_found("Cliente inexistente.")
    if servicio is None:
        raise not_found("Servicio inexistente o inactivo.")
    validate_contact(cliente)
    inicio_dt = to_utc(data.inicio)
    validate_time(inicio_dt, now)
    inicio, fin = fmt(inicio_dt), fmt(inicio_dt + timedelta(minutes=servicio["duracion_min"]))
    assert_no_overlap(conn, "profesional_id", servicio["profesional_id"], inicio, fin)
    assert_no_overlap(conn, "cliente_id", cliente["id"], inicio, fin)
    turno_id, ts = str(uuid.uuid4()), fmt(now)
    conn.execute(
        "INSERT INTO turno (id, cliente_id, profesional_id, servicio_id, inicio, fin, estado, creado_en, actualizado_en)"
        " VALUES (?,?,?,?,?,?,'CONFIRMADO',?,?)",
        (turno_id, cliente["id"], servicio["profesional_id"], servicio["id"], inicio, fin, ts, ts),
    )
    return conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)).fetchone()


def cancel_turno(conn: sqlite3.Connection, turno_id: str, data: CancelarIn, now: datetime) -> sqlite3.Row:
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
    init_db()  # crea las tablas al iniciar el servidor
    yield


app = FastAPI(title="Turnos Pro API", version="0.2.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": exc.code, "detalle": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=422, content={"error": "INVALID_REQUEST", "detalle": detail})


@app.get("/api/turnos", response_model=list[TurnoOut])
def listar_turnos(
    cliente_id: Optional[str] = None,
    profesional_id: Optional[str] = None,
    estado: Optional[Estado] = Query(default=None),
) -> list[TurnoOut]:
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
        return [turno_out(r) for r in conn.execute(sql, params).fetchall()]


@app.post("/api/turnos", response_model=TurnoOut, status_code=201)
def crear_turno(data: TurnoCreate) -> TurnoOut:
    with write_tx() as conn:
        return turno_out(create_turno(conn, data, utcnow()))


@app.post("/api/turnos/{turno_id}/cancelar", response_model=TurnoOut)
def cancelar_turno(turno_id: str, data: CancelarIn) -> TurnoOut:
    with write_tx() as conn:
        return turno_out(cancel_turno(conn, turno_id, data, utcnow()))
