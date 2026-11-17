"""Capa de negocio, adaptador HTTP (FastAPI, puerto 8000). Contrato: spec.md §11; capas: spec.md §12 (v2.2.0).

Responsabilidades (spec §12.1): rutas de §11, CORS, actor por `X-Usuario-Id`, traducción de errores a §11.1.
No ejecuta SQL (ARQ-05): el esquema de `turnos.db` lo crea `db.py` al arrancar y las consultas viven en `service.py`.

Arranque con recarga automática (desde backend/):
    python -m uvicorn main:app --reload --port 8000
Swagger UI: http://localhost:8000/docs
"""
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

import config
import db
import schemas
import seed
import service
from domain import HTTP, ErrorDominio


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crea el esquema de spec §4.1 (plan §3.3.1) en turnos.db si no existe y siembra si la base está vacía.
    seed.sembrar_si_vacia(config.DB_PATH)
    yield


app = FastAPI(
    title="Sistema de Turnos",
    version="2.2.0",
    description="Contrato de spec.md §11. El actor se identifica con el encabezado `X-Usuario-Id` (D-06).",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=config.CORS_METHODS,
                   allow_headers=config.CORS_HEADERS)


# ---------------------------------------------------------------- errores (§11.1)
def error(codigo: str, mensaje: str) -> JSONResponse:
    return JSONResponse({"error": {"codigo": codigo, "mensaje": mensaje}}, status_code=HTTP[codigo])


@app.exception_handler(ErrorDominio)
async def error_dominio(_: Request, e: ErrorDominio) -> JSONResponse:
    r = error(e.codigo, e.mensaje)
    if e.detalles and "conflictos" in e.detalles:          # única extensión permitida (§11.1, RN-05)
        r = JSONResponse({"error": {"codigo": e.codigo, "mensaje": e.mensaje, "conflictos": e.detalles["conflictos"]}},
                         status_code=e.http)
    return r


@app.exception_handler(RequestValidationError)
async def error_validacion(_: Request, e: RequestValidationError) -> JSONResponse:
    detalle = "; ".join(f"{'.'.join(str(x) for x in err['loc'][1:]) or 'cuerpo'}: {err['msg']}" for err in e.errors())
    return error("VALIDATION_ERROR", f"Solicitud mal formada. {detalle}")


@app.exception_handler(sqlite3.Error)
async def error_persistencia(_: Request, e: sqlite3.Error) -> JSONResponse:
    # INV-03: la transacción ya hizo ROLLBACK; no quedan escrituras parciales.
    codigo = str(e).split(":")[0]
    if codigo in HTTP and codigo != "PERSISTENCE_UNAVAILABLE":   # RAISE(ABORT, '<código>') de un trigger
        return error(codigo, "La base de datos rechazó la operación.")
    return error("PERSISTENCE_UNAVAILABLE", "No se pudo acceder a la base de datos. Intentá de nuevo en unos segundos.")


# ---------------------------------------------------------------- dependencias
def conexion() -> Iterator[sqlite3.Connection]:
    # Una conexión por solicitud: SQLite serializa a los escritores con BEGIN IMMEDIATE.
    conn = db.connect(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


Conexion = Annotated[sqlite3.Connection, Depends(conexion)]


def actor(conn: Conexion, x_usuario_id: Annotated[str | None, Header()] = None) -> sqlite3.Row:
    return service.actor_por_id(conn, x_usuario_id)


Actor = Annotated[sqlite3.Row, Depends(actor)]


# ---------------------------------------------------------------- raíz (conveniencia, fuera del contrato §11)
@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    """Abrir http://localhost:8000/ lleva a la documentación interactiva de la API."""
    return RedirectResponse(url="/docs")


# ---------------------------------------------------------------- §11.3 – §11.5
@app.get("/api/turnos", response_model=list[schemas.Turno], responses=schemas.errores(401, 422, 503), tags=["turnos"])
def listar_turnos(conn: Conexion, yo: Actor, estado: schemas.Estado | None = None, profesional_id: str | None = None,
                  desde: str | None = None, hasta: str | None = None) -> list[dict[str, Any]]:
    """§11.3: turnos visibles para el actor según su rol (RBAC-01), por `inicio` ascendente."""
    return service.listar_turnos(conn, yo, estado, profesional_id, desde, hasta)


@app.post("/api/turnos", status_code=201, response_model=schemas.Turno,
          responses=schemas.errores(401, 403, 404, 409, 422, 503), tags=["turnos"])
def crear_turno(body: schemas.ReservaIn, conn: Conexion, yo: Actor, response: Response) -> dict[str, Any]:
    """§11.4: 409 `SLOT_UNAVAILABLE` si choca (INV-02). El 201 sale después del COMMIT (INV-03)."""
    turno = service.crear_turno(conn, yo, str(body.servicio_id), body.inicio,
                                str(body.cliente_id) if body.cliente_id else None)
    response.headers["Location"] = f"/api/turnos/{turno['id']}"
    return turno


@app.post("/api/turnos/{turno_id}/cancelar", response_model=schemas.Turno,
          responses=schemas.errores(401, 404, 409, 422, 503), tags=["turnos"])
def cancelar_turno(turno_id: str, conn: Conexion, yo: Actor, body: schemas.CancelacionIn | None = None) -> dict[str, Any]:
    """§11.5: 409 `CANCELLATION_WINDOW_EXPIRED` si el cliente cancela a menos de 2 h (INV-01)."""
    return service.cancelar_turno(conn, yo, turno_id, body.motivo if body else None)


# ---------------------------------------------------------------- v2.1.0: §11.6 – §11.13
def actor_opcional(conn: Conexion, x_usuario_id: Annotated[str | None, Header()] = None) -> sqlite3.Row | None:
    """§11.1: las lecturas públicas aceptan Anónimo; un encabezado inválido sigue siendo 401."""
    return service.actor_por_id(conn, x_usuario_id) if x_usuario_id is not None else None


ActorOpcional = Annotated[sqlite3.Row | None, Depends(actor_opcional)]


@app.get("/api/servicios", response_model=list[schemas.Servicio], responses=schemas.errores(401, 503), tags=["catálogo"])
def listar_servicios(conn: Conexion, _yo: ActorOpcional) -> list[dict[str, Any]]:
    """§11.6 (F-02): catálogo público, incluidos los servicios desactivados."""
    return service.listar_servicios(conn)


@app.post("/api/servicios/{servicio_id}/activar", response_model=schemas.Servicio,
          responses=schemas.errores(401, 403, 404, 503), tags=["catálogo"])
def activar_servicio(servicio_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.7 (RN-07)."""
    return service.cambiar_activo_servicio(conn, yo, servicio_id, True)


@app.post("/api/servicios/{servicio_id}/desactivar", response_model=schemas.Servicio,
          responses=schemas.errores(401, 403, 404, 503), tags=["catálogo"])
def desactivar_servicio(servicio_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.7 (RN-07): baja lógica; los turnos confirmados no cambian."""
    return service.cambiar_activo_servicio(conn, yo, servicio_id, False)


@app.get("/api/horarios", response_model=list[schemas.HorarioLaboral], responses=schemas.errores(401, 503), tags=["catálogo"])
def listar_horarios(conn: Conexion, _yo: ActorOpcional, profesional_id: str | None = None) -> list[dict[str, Any]]:
    """§11.8 (F-08): horario laboral público."""
    return service.listar_horarios(conn, profesional_id)


@app.post("/api/horarios", response_model=list[schemas.HorarioLaboral],
          responses=schemas.errores(401, 403, 404, 422, 503), tags=["catálogo"])
def reemplazar_horario(body: schemas.HorarioIn, conn: Conexion, yo: Actor) -> list[dict[str, Any]]:
    """§11.8 (F-08, D-09): reemplaza el horario semanal completo del profesional."""
    franjas = [(f.dia_semana, f.hora_inicio, f.hora_fin) for f in body.franjas]
    return service.reemplazar_horario(conn, yo, str(body.profesional_id), franjas)


@app.get("/api/disponibilidad", response_model=list[schemas.Slot], responses=schemas.errores(401, 404, 409, 422, 503),
         tags=["catálogo"])
def disponibilidad(conn: Conexion, _yo: ActorOpcional, servicio_id: str, fecha: str) -> list[dict[str, str]]:
    """§11.9 (F-03): slots libres considerando los turnos de todos los clientes."""
    return service.disponibilidad(conn, servicio_id, fecha)


@app.get("/api/bloqueos", response_model=list[schemas.Bloqueo], responses=schemas.errores(401, 403, 503), tags=["agenda"])
def listar_bloqueos(conn: Conexion, yo: Actor, profesional_id: str | None = None) -> list[dict[str, Any]]:
    """§11.10 (F-09)."""
    return service.listar_bloqueos(conn, yo, profesional_id)


@app.post("/api/bloqueos", status_code=201, response_model=schemas.BloqueoCreado,
          responses=schemas.errores(401, 403, 404, 409, 422, 503), tags=["agenda"])
def crear_bloqueo(body: schemas.BloqueoIn, conn: Conexion, yo: Actor, response: Response) -> dict[str, Any]:
    """§11.10 (RN-05): 409 `SLOT_UNAVAILABLE` con `conflictos` si hay turnos y no se confirmó su cancelación."""
    r = service.crear_bloqueo(conn, yo, str(body.profesional_id), body.inicio, body.fin, body.motivo,
                              body.confirmar_cancelacion)
    response.headers["Location"] = f"/api/bloqueos/{r['bloqueo']['id']}"
    return r


@app.post("/api/bloqueos/{bloqueo_id}/eliminar", response_model=schemas.Bloqueo,
          responses=schemas.errores(401, 403, 404, 503), tags=["agenda"])
def eliminar_bloqueo(bloqueo_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.10."""
    return service.eliminar_bloqueo(conn, yo, bloqueo_id)


@app.post("/api/turnos/{turno_id}/completar", response_model=schemas.Turno,
          responses=schemas.errores(401, 403, 404, 409, 503), tags=["turnos"])
def completar_turno(turno_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.11 (RN-06): desde el inicio del turno."""
    return service.cerrar_turno(conn, yo, turno_id, "COMPLETADO")


@app.post("/api/turnos/{turno_id}/ausente", response_model=schemas.Turno,
          responses=schemas.errores(401, 403, 404, 409, 503), tags=["turnos"])
def marcar_ausente(turno_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.11 (RN-06): una vez finalizado el turno."""
    return service.cerrar_turno(conn, yo, turno_id, "AUSENTE")


@app.get("/api/auditoria", response_model=list[schemas.AuditoriaEvento], responses=schemas.errores(401, 403, 503),
         tags=["agenda"])
def auditoria(conn: Conexion, yo: Actor) -> list[dict[str, Any]]:
    """§11.12 (RN-08): solo lectura."""
    return service.auditoria(conn, yo)


@app.get("/api/metricas", response_model=schemas.Metricas, responses=schemas.errores(401, 403, 404, 422, 503),
         tags=["agenda"])
def metricas(conn: Conexion, yo: Actor, desde: str, hasta: str, profesional_id: str | None = None) -> dict[str, Any]:
    """§11.13 (F-12, §5)."""
    return service.metricas(conn, yo, desde, hasta, profesional_id)
