"""Notificaciones salientes por webhook (spec §16, INV-07).

Se ejecuta en segundo plano, después del COMMIT: nada de lo que pase aquí afecta a la transacción del turno
ni a la respuesta al cliente. La entrega es de mejor esfuerzo (sin cola persistente).

Configuración: `WEBHOOK_NOTIFY_URL` en `.env` o en el entorno; vacía = webhooks desactivados.
La URL nunca se imprime ni se guarda, porque puede contener un token.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Optional

import httpx
from dotenv import load_dotenv

TIMEOUT_SEGUNDOS = 3.0
ESPERAS = (1, 2, 4)  # segundos antes de cada reintento: 1 intento original + 3 reintentos

logger = logging.getLogger("webhooks")
if not logger.handlers:  # uvicorn no muestra los INFO de otros loggers: salida propia a consola
    _consola = logging.StreamHandler()
    _consola.setFormatter(logging.Formatter("%(levelname)s:     [webhook] %(message)s"))
    logger.addHandler(_consola)
    logger.setLevel(logging.INFO)


def _crear_cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS)


def _guardar_resultado(evento: str, turno_id: Optional[str], estado: str, intentos: int,
                       codigo_http: Optional[int], error: Optional[str]) -> None:
    import main  # import diferido: main importa este módulo

    with main.write_tx() as conn:
        conn.execute(
            "INSERT INTO webhook_logs (id, timestamp, evento, turno_id, estado, intentos, codigo_http, error)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), main.fmt(main.utcnow()), evento, turno_id, estado, intentos, codigo_http, error),
        )


async def enviar_notificacion_webhook(evento: str, payload: dict) -> None:
    """Envía `{"evento": evento, "turno": payload}` por POST. Nunca lanza.

    Reintenta (esperas de 1, 2 y 4 s) ante error de red, timeout o status >= 500. Cualquier otro status
    distinto de 2xx es un fallo definitivo. El resultado final se guarda en `webhook_logs`.
    """
    load_dotenv()  # no pisa variables ya definidas en el entorno
    url = os.environ.get("WEBHOOK_NOTIFY_URL", "").strip()
    turno_id = payload.get("id")
    if not url:
        logger.info("WEBHOOK_NOTIFY_URL vacía: no se envía %s (turno %s).", evento, turno_id)
        return

    intentos, codigo, error, entregado = 0, None, None, False
    try:
        async with _crear_cliente() as cliente:
            for espera in (0, *ESPERAS):
                if espera:
                    await asyncio.sleep(espera)
                intentos += 1
                codigo, error = None, None
                try:
                    # wait_for: tope total del intento (el timeout de httpx es por operación de red)
                    resp = await asyncio.wait_for(
                        cliente.post(url, json={"evento": evento, "turno": payload}), TIMEOUT_SEGUNDOS
                    )
                    codigo = resp.status_code
                    entregado = resp.is_success
                    if not entregado:
                        error = f"HTTP {codigo}"
                except Exception as exc:  # red, DNS, timeout, URL inválida
                    error = type(exc).__name__
                logger.info("%s turno %s: intento %d/%d -> %s", evento, turno_id, intentos,
                            1 + len(ESPERAS), "entregado" if entregado else error)
                if entregado or (codigo is not None and codigo < 500):
                    break
    except Exception as exc:  # p. ej. no se pudo crear el cliente
        error = type(exc).__name__
        intentos = max(intentos, 1)

    estado = "entregado" if entregado else "fallido"
    logger.log(logging.INFO if entregado else logging.ERROR, "%s turno %s: %s tras %d intento(s).",
               evento, turno_id, estado, intentos)
    try:
        await asyncio.to_thread(_guardar_resultado, evento, turno_id, estado, intentos, codigo, error)
    except Exception:
        logger.exception("No se pudo guardar el resultado en webhook_logs.")
