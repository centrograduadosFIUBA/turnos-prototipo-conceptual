"""Adaptador HTTP de la capa de negocio (FastAPI, puerto 8000).

Contrato: spec.md §11 · Arquitectura: spec.md §12.

Responsabilidades (spec §12.1):
- Exponer las rutas de la §11 y documentarlas en Swagger UI.
- Aplicar CORS con la lista explícita de `config.py`.
- Identificar al actor por el encabezado `X-Usuario-Id` (D-06).
- Traducir los errores de dominio y de la base al formato de la §11.1.

No ejecuta SQL (ARQ-05): el esquema lo crea `db.py` al arrancar y las consultas viven en `service.py`.

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

DESCRIPCION_API = """
API del **Sistema de Turnos**. Contrato normativo: `spec.md` §11.

**Identidad.** Cada solicitud indica el usuario que actúa con el encabezado `X-Usuario-Id` (UUID).
El rol (`CLIENTE`, `PROFESIONAL`, `ADMIN`) lo lee el servidor de la base; nunca se toma del cliente.
Las lecturas públicas (catálogo, horarios y disponibilidad) aceptan solicitudes sin encabezado.

**Errores.** Todas las respuestas de error tienen la forma
`{"error": {"codigo": "...", "mensaje": "..."}}`, con `codigo` del catálogo de la §7.

**Fechas.** Todos los instantes viajan en ISO 8601 UTC con sufijo `Z`.
"""

ETIQUETAS = [
    {"name": "turnos", "description": "Reservar, listar, cancelar y cerrar turnos (INV-01, INV-02, INV-03, RN-06)."},
    {"name": "catálogo", "description": "Servicios, horario laboral y disponibilidad. Lecturas públicas."},
    {"name": "agenda", "description": "Bloqueos, auditoría y métricas del profesional o del administrador."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Al arrancar: crea el esquema de spec §4.1 en `turnos.db` si no existe y lo siembra si está vacío."""
    seed.sembrar_si_vacia(config.DB_PATH)
    yield


app = FastAPI(
    title="Sistema de Turnos",
    version="2.3.2",
    description=DESCRIPCION_API,
    openapi_tags=ETIQUETAS,
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=config.CORS_METHODS,
                   allow_headers=config.CORS_HEADERS)


# ================================================================ errores (§11.1)
def respuesta_de_error(codigo: str, mensaje: str) -> JSONResponse:
    """Cuerpo de error de la §11.1 con el status HTTP que le asigna el catálogo de la §7."""
    return JSONResponse({"error": {"codigo": codigo, "mensaje": mensaje}}, status_code=HTTP[codigo])


@app.exception_handler(ErrorDominio)
async def manejar_error_de_dominio(_: Request, e: ErrorDominio) -> JSONResponse:
    """Regla de negocio violada. Solo el error de RN-05 agrega la lista `conflictos` (§11.1)."""
    if e.detalles and "conflictos" in e.detalles:
        return JSONResponse(
            {"error": {"codigo": e.codigo, "mensaje": e.mensaje, "conflictos": e.detalles["conflictos"]}},
            status_code=e.http)
    return respuesta_de_error(e.codigo, e.mensaje)


@app.exception_handler(RequestValidationError)
async def manejar_cuerpo_mal_formado(_: Request, e: RequestValidationError) -> JSONResponse:
    """Pydantic rechazó la solicitud: 422 `VALIDATION_ERROR` indicando qué campo falló."""
    detalle = "; ".join(f"{'.'.join(str(x) for x in err['loc'][1:]) or 'cuerpo'}: {err['msg']}" for err in e.errors())
    return respuesta_de_error("VALIDATION_ERROR", f"Solicitud mal formada. {detalle}")


@app.exception_handler(sqlite3.Error)
async def manejar_error_de_base(_: Request, e: sqlite3.Error) -> JSONResponse:
    """Error de SQLite, siempre después del ROLLBACK (INV-03): no quedan escrituras parciales.

    Si lo levantó un trigger con `RAISE(ABORT, '<código>')` y el código es de la §7, se devuelve ese código
    (ARQ-06). Cualquier otro fallo es 503 `PERSISTENCE_UNAVAILABLE`.
    """
    codigo = str(e).split(":")[0]
    if codigo in HTTP and codigo != "PERSISTENCE_UNAVAILABLE":
        return respuesta_de_error(codigo, "La base de datos rechazó la operación.")
    return respuesta_de_error("PERSISTENCE_UNAVAILABLE",
                              "No se pudo acceder a la base de datos. Intentá de nuevo en unos segundos.")


# ================================================================ dependencias
def abrir_conexion() -> Iterator[sqlite3.Connection]:
    """Una conexión por solicitud; SQLite serializa a los escritores con BEGIN IMMEDIATE."""
    conn = db.connect(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


Conexion = Annotated[sqlite3.Connection, Depends(abrir_conexion)]

EncabezadoUsuario = Annotated[str | None, Header(description="UUID del usuario que actúa (D-06).")]


def actor_obligatorio(conn: Conexion, x_usuario_id: EncabezadoUsuario = None) -> sqlite3.Row:
    """Usuario activo del encabezado `X-Usuario-Id`. Sin encabezado, o con uno inválido: 401."""
    return service.actor_por_id(conn, x_usuario_id)


def actor_opcional(conn: Conexion, x_usuario_id: EncabezadoUsuario = None) -> sqlite3.Row | None:
    """Para lecturas públicas (§11.1): sin encabezado es Anónimo; con uno inválido sigue siendo 401."""
    return service.actor_por_id(conn, x_usuario_id) if x_usuario_id is not None else None


Actor = Annotated[sqlite3.Row, Depends(actor_obligatorio)]
ActorOpcional = Annotated[sqlite3.Row | None, Depends(actor_opcional)]


# ================================================================ raíz (fuera del contrato §11)
@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    """Abrir http://localhost:8000/ lleva a la documentación interactiva."""
    return RedirectResponse(url="/docs")


# ================================================================ turnos (§11.3 – §11.5, §11.11)
@app.get("/api/turnos", tags=["turnos"], summary="Listar turnos",
         response_model=list[schemas.Turno], responses=schemas.errores(401, 422, 503))
def listar_turnos(conn: Conexion, yo: Actor, estado: schemas.Estado | None = None,
                  profesional_id: str | None = None, desde: str | None = None,
                  hasta: str | None = None) -> list[dict[str, Any]]:
    """§11.3 · Turnos que el actor puede ver según su rol (RBAC-01), ordenados por `inicio`.

    - `CLIENTE`: solo los suyos.
    - `PROFESIONAL`: los de su agenda.
    - `ADMIN`: todos.

    Filtros opcionales: `estado`, `profesional_id` y el rango `desde` / `hasta` (ISO 8601 UTC).
    """
    return service.listar_turnos(conn, yo, estado, profesional_id, desde, hasta)


@app.post("/api/turnos", tags=["turnos"], summary="Reservar un turno", status_code=201,
          response_model=schemas.Turno, responses=schemas.errores(401, 403, 404, 409, 422, 503))
def crear_turno(body: schemas.ReservaIn, conn: Conexion, yo: Actor, response: Response) -> dict[str, Any]:
    """§11.4 · Crea un turno `CONFIRMADO`. `fin` y `profesional_id` los calcula el servidor a partir del servicio.

    - `409 SLOT_UNAVAILABLE`: choca con otro turno, con un bloqueo o con otro turno del mismo cliente (INV-02).
    - `422 INVALID_TIME_RANGE`: pasado, sin la antelación mínima, fuera de grilla, del horizonte o del horario.
    - `422 VALIDATION_ERROR`: cuerpo mal formado (campos vacíos, faltantes, de tipo incorrecto o no permitidos).

    El `201` se envía después del COMMIT (INV-03), con el encabezado `Location`.
    """
    turno = service.crear_turno(conn, yo, str(body.servicio_id), body.inicio,
                                str(body.cliente_id) if body.cliente_id else None)
    response.headers["Location"] = f"/api/turnos/{turno['id']}"
    return turno


@app.post("/api/turnos/{turno_id}/cancelar", tags=["turnos"], summary="Cancelar un turno",
          response_model=schemas.Turno, responses=schemas.errores(401, 404, 409, 422, 503))
def cancelar_turno(turno_id: str, conn: Conexion, yo: Actor,
                   body: schemas.CancelacionIn | None = None) -> dict[str, Any]:
    """§11.5 · Pasa un turno `CONFIRMADO` que todavía no empezó a `CANCELADO`. El turno no se borra.

    - `CLIENTE`: solo los suyos y con al menos 2 h de anticipación; si no, `409 CANCELLATION_WINDOW_EXPIRED` (INV-01).
    - `PROFESIONAL` / `ADMIN`: sin ventana, pero con `motivo` obligatorio (`422 REASON_REQUIRED`).
    - `404 NOT_FOUND`: el turno no existe o el actor no tiene acceso a él (RBAC-02).
    - `409 INVALID_STATE_TRANSITION`: el turno ya estaba cancelado, cerrado o ya comenzó (RN-06).
    """
    return service.cancelar_turno(conn, yo, turno_id, body.motivo if body else None)


@app.post("/api/turnos/{turno_id}/completar", tags=["turnos"], summary="Marcar un turno como completado",
          response_model=schemas.Turno, responses=schemas.errores(401, 403, 404, 409, 503))
def completar_turno(turno_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.11 (RN-06) · `PROFESIONAL` o `ADMIN`, a partir del `inicio` del turno."""
    return service.cerrar_turno(conn, yo, turno_id, "COMPLETADO")


@app.post("/api/turnos/{turno_id}/ausente", tags=["turnos"], summary="Marcar al cliente como ausente",
          response_model=schemas.Turno, responses=schemas.errores(401, 403, 404, 409, 503))
def marcar_ausente(turno_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.11 (RN-06) · `PROFESIONAL` o `ADMIN`, una vez pasado el `fin` del turno."""
    return service.cerrar_turno(conn, yo, turno_id, "AUSENTE")


# ================================================================ catálogo (§11.6 – §11.9)
@app.get("/api/servicios", tags=["catálogo"], summary="Listar servicios",
         response_model=list[schemas.Servicio], responses=schemas.errores(401, 503))
def listar_servicios(conn: Conexion, _yo: ActorOpcional) -> list[dict[str, Any]]:
    """§11.6 (F-02) · Catálogo público, incluidos los servicios desactivados (`activo = false`)."""
    return service.listar_servicios(conn)


@app.post("/api/servicios/{servicio_id}/activar", tags=["catálogo"], summary="Activar un servicio",
          response_model=schemas.Servicio, responses=schemas.errores(401, 403, 404, 503))
def activar_servicio(servicio_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.7 (RN-07) · Vuelve a ofrecer el servicio para nuevas reservas."""
    return service.cambiar_activo_servicio(conn, yo, servicio_id, True)


@app.post("/api/servicios/{servicio_id}/desactivar", tags=["catálogo"], summary="Desactivar un servicio",
          response_model=schemas.Servicio, responses=schemas.errores(401, 403, 404, 503))
def desactivar_servicio(servicio_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.7 (RN-07) · Baja lógica: no admite reservas nuevas y los turnos ya confirmados no cambian."""
    return service.cambiar_activo_servicio(conn, yo, servicio_id, False)


@app.get("/api/horarios", tags=["catálogo"], summary="Listar el horario laboral",
         response_model=list[schemas.HorarioLaboral], responses=schemas.errores(401, 503))
def listar_horarios(conn: Conexion, _yo: ActorOpcional, profesional_id: str | None = None) -> list[dict[str, Any]]:
    """§11.8 (F-08) · Franjas semanales de atención, públicas. Filtro opcional por `profesional_id`."""
    return service.listar_horarios(conn, profesional_id)


@app.post("/api/horarios", tags=["catálogo"], summary="Reemplazar el horario laboral",
          response_model=list[schemas.HorarioLaboral], responses=schemas.errores(401, 403, 404, 422, 503))
def reemplazar_horario(body: schemas.HorarioIn, conn: Conexion, yo: Actor) -> list[dict[str, Any]]:
    """§11.8 (F-08, D-09) · Reemplaza el horario semanal completo del profesional por las franjas enviadas."""
    franjas = [(f.dia_semana, f.hora_inicio, f.hora_fin) for f in body.franjas]
    return service.reemplazar_horario(conn, yo, str(body.profesional_id), franjas)


@app.get("/api/disponibilidad", tags=["catálogo"], summary="Consultar horarios libres",
         response_model=list[schemas.Slot], responses=schemas.errores(401, 404, 409, 422, 503))
def disponibilidad(conn: Conexion, _yo: ActorOpcional, servicio_id: str, fecha: str) -> list[dict[str, str]]:
    """§11.9 (F-03) · Slots libres de un servicio en una `fecha` (AAAA-MM-DD).

    Considera los turnos de todos los clientes, los bloqueos y el horario laboral, sin revelar quién reservó.
    """
    return service.disponibilidad(conn, servicio_id, fecha)


# ================================================================ agenda (§11.10, §11.12, §11.13)
@app.get("/api/bloqueos", tags=["agenda"], summary="Listar bloqueos",
         response_model=list[schemas.Bloqueo], responses=schemas.errores(401, 403, 503))
def listar_bloqueos(conn: Conexion, yo: Actor, profesional_id: str | None = None) -> list[dict[str, Any]]:
    """§11.10 (F-09) · `PROFESIONAL`: los suyos. `ADMIN`: todos. `CLIENTE`: 403."""
    return service.listar_bloqueos(conn, yo, profesional_id)


@app.post("/api/bloqueos", tags=["agenda"], summary="Crear un bloqueo", status_code=201,
          response_model=schemas.BloqueoCreado, responses=schemas.errores(401, 403, 404, 409, 422, 503))
def crear_bloqueo(body: schemas.BloqueoIn, conn: Conexion, yo: Actor, response: Response) -> dict[str, Any]:
    """§11.10 (RN-05) · Reserva un rango de la agenda en el que no se aceptan turnos.

    Si hay turnos confirmados en el rango y no se envió `confirmar_cancelacion = true`, responde
    `409 SLOT_UNAVAILABLE` con la lista `conflictos`. Con la confirmación, cancela esos turnos y crea el bloqueo
    en la misma transacción.
    """
    resultado = service.crear_bloqueo(conn, yo, str(body.profesional_id), body.inicio, body.fin, body.motivo,
                                      body.confirmar_cancelacion)
    response.headers["Location"] = f"/api/bloqueos/{resultado['bloqueo']['id']}"
    return resultado


@app.post("/api/bloqueos/{bloqueo_id}/eliminar", tags=["agenda"], summary="Eliminar un bloqueo",
          response_model=schemas.Bloqueo, responses=schemas.errores(401, 403, 404, 503))
def eliminar_bloqueo(bloqueo_id: str, conn: Conexion, yo: Actor) -> dict[str, Any]:
    """§11.10 · Libera el rango bloqueado. Los turnos cancelados por el bloqueo no se restauran."""
    return service.eliminar_bloqueo(conn, yo, bloqueo_id)


@app.get("/api/auditoria", tags=["agenda"], summary="Consultar la auditoría",
         response_model=list[schemas.AuditoriaEvento], responses=schemas.errores(401, 403, 503))
def auditoria(conn: Conexion, yo: Actor) -> list[dict[str, Any]]:
    """§11.12 (RN-08) · Eventos registrados, de solo lectura. Un `CLIENTE` recibe 403."""
    return service.auditoria(conn, yo)


@app.get("/api/metricas", tags=["agenda"], summary="Consultar métricas",
         response_model=schemas.Metricas, responses=schemas.errores(401, 403, 404, 422, 503))
def metricas(conn: Conexion, yo: Actor, desde: str, hasta: str, profesional_id: str | None = None) -> dict[str, Any]:
    """§11.13 (F-12, §5) · Conteos, tasas y ocupación en el período `desde` / `hasta`.

    Un `PROFESIONAL` solo ve las suyas.
    """
    return service.metricas(conn, yo, desde, hasta, profesional_id)
