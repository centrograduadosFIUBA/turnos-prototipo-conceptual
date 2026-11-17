# tareas.md — Tareas por fase para ejecutar [plan.md](plan.md)

> Las fases 0 a 8 corresponden al prototipo en memoria de la Fase 1 del curso (`index.html`), según la versión anterior del plan (disponible en el historial de git). Las tareas de la **Fase 2 del curso** (arquitectura desacoplada, plan.md v2.0.0) están en las fases B1 a B7, al final.

Leyenda: `[ ]` pendiente · `[x]` hecho · **Salida** = entregable de la fase · **Hecho cuando** = criterio de cierre.
Cada fase depende de la anterior. Las referencias (`RN-xx`, `ERR-xx`, `HU-xx`) apuntan a [spec.md](spec.md) y [historias-de-usuario.md](historias-de-usuario.md).

---

## Fase 0 — Preparación

- [x] 0.1 Confirmar con el usuario la aprobación del plan y las 5 decisiones por defecto (plan §7).
- [x] 0.2 Cargar la guía `artifact-design` (tokens en `:root`, modo oscuro, layout móvil, título de 2 a 4 palabras).
- [x] 0.3 Definir el archivo de trabajo del prototipo (`prototipo-turnos.html`) y las versiones fijas de React, Babel y Lucide. _(Hecho con variación: el archivo es `index.html` y Lucide va como SVG inline.)_
- [x] 0.4 Definir las constantes de configuración del spec: ventana 2 h, antelación 1 h, horizonte 60 días, grilla 15 min.

**Salida:** archivo vacío con el esqueleto HTML, CDNs y tokens de tema.
**Hecho cuando:** la página carga sin errores en claro y oscuro.

---

## Fase 1 — Dominio puro (`domain/`)

- [x] 1.1 Utilidades de tiempo: sumar minutos, alinear a la grilla, comparar intervalos `[inicio, fin)`.
- [x] 1.2 `overlaps(a, b)`: solapamiento con contigüidad válida (RN-02).
- [x] 1.3 `computeSlots(profesional, servicio, fecha, estado, ahora)`: respeta horario laboral, turnos activos, bloqueos, antelación mínima, horizonte y que el servicio entre antes del fin de jornada (HU-01, EC-01.1 a EC-01.4).
- [x] 1.4 `validateContact(usuario)`: nombre, email, teléfono, email verificado (RN-03).
- [x] 1.5 `canClientCancel(turno, ahora)`: ventana de 2 h con límite exacto inclusivo (RN-01, EC-04.2).
- [x] 1.6 `transition(turno, accion, actor)`: tabla de transiciones y estados terminales (RN-06). _(Hecho con variación: sin función `transition`; la tabla de transiciones está repartida en `completeAppointment`, `markNoShow` y `applyCancel`.)_
- [x] 1.7 `bookAppointment`, `cancelAppointment`, `completeAppointment`, `markNoShow`, `createBlock`, `removeBlock`: cada una devuelve `{ok, estado}` o `{error: CODIGO}` usando el catálogo del spec §7.
- [x] 1.8 `createBlock` con detección de conflictos: lista los turnos afectados y, con confirmación, cancela y bloquea en una sola operación (RN-05, EC-06.2).
- [x] 1.9 Generación de eventos de auditoría y de correos simulados (RN-08, F-13).
- [ ] 1.10 Autoverificación en consola: casos de prueba rápidos de las funciones puras (solapamiento parcial, contiguo, límite 2 h, bloqueo).

**Salida:** módulo de dominio sin dependencias de React.
**Hecho cuando:** los casos de 1.10 pasan en la consola del navegador.

---

## Fase 2 — Datos mock y estado

- [x] 2.1 Semillas relativas a "hoy": 3 profesionales, 5 o 6 servicios (30, 45, 60 min), horario de lunes a viernes.
- [x] 2.2 Dos clientes, uno con email sin verificar (para `EMAIL_NOT_VERIFIED`) y un `ADMIN`.
- [x] 2.3 Unos 12 turnos con estados variados, incluyendo uno a 1 h 59 min y otro a 3 h de "ahora".
- [x] 2.4 1 o 2 bloqueos de ejemplo.
- [x] 2.5 Reloj simulado en el estado (`ahora`), con acciones `+1 h`, `+1 día` y reinicio.
- [x] 2.6 Reducer centralizado que invoca las funciones de la Fase 1 y devuelve errores de dominio sin mutar el estado. _(Hecho con variación: lo cubre `act()` con funciones de dominio puras, sin reducer.)_
- [x] 2.7 `Context` con `dispatch`, usuario activo, rol activo y cola de toasts.
- [x] 2.8 Acción "Reiniciar datos".

**Salida:** `store` funcional con una sola fuente de verdad.
**Hecho cuando:** despachar acciones desde la consola cambia el estado y respeta las reglas.

---

## Fase 3 — Componentes compartidos (`ui/`)

- [x] 3.1 Barra superior: selector Cliente/Administrador, selector de cliente activo, selector Profesional/ADMIN en vista Administrador, reloj simulado y botones de tiempo.
- [x] 3.2 Badges de estado (`CONFIRMADO`, `CANCELADO`, `COMPLETADO`, `AUSENTE`) con color y texto, no solo color.
- [x] 3.3 Modal reutilizable accesible (foco, `Esc`, etiquetas).
- [x] 3.4 Toasts para éxito y para errores de dominio con su código.
- [x] 3.5 Panel lateral colapsable de "Bandeja simulada" (emails de confirmación y cancelación).
- [x] 3.6 Layout responsive con gutters de 16 px y sin scroll horizontal.

**Salida:** estructura de la aplicación con navegación por rol.
**Hecho cuando:** alternar el rol cambia la vista y la barra muestra el contexto correcto.

---

## Fase 4 — Vista Cliente (Flujo 1)

- [x] 4.1 Selector de servicio, profesional y fecha (limitado al horizonte de 60 días) (HU-01).
- [x] 4.2 Grilla de slots libres calculada por `computeSlots`, con estado vacío cuando no hay.
- [x] 4.3 Modal de confirmación con resumen y formulario de contacto editable con validación (HU-02, RN-03).
- [x] 4.4 Envío de la reserva por el reducer, con deshabilitado del botón durante el envío para evitar doble clic (ERR-02.3).
- [x] 4.5 Pantalla de confirmación con servicio, profesional, inicio y fin, y aviso de la política de cancelación (HU-03).
- [x] 4.6 "Mis turnos": próximos e historial, solo del cliente activo (RBAC-02).
- [x] 4.7 Botón Cancelar deshabilitado con tooltip a menos de 2 h, y mensaje `CANCELLATION_WINDOW_EXPIRED` si se fuerza (HU-04).
- [x] 4.8 Mensajes claros para `SLOT_UNAVAILABLE`, `INVALID_CONTACT`, `EMAIL_NOT_VERIFIED`, `INVALID_TIME_RANGE`, y acción "Reenviar verificación".

**Salida:** flujo completo de reserva, confirmación y cancelación del cliente.
**Hecho cuando:** un cliente reserva, ve el turno en "Mis turnos" y el slot desaparece de la grilla.

---

## Fase 5 — Vista Administrador (Flujo 2)

- [x] 5.1 Agenda día/semana y vista de lista, filtrada por profesional según el rol (PROFESIONAL ve lo suyo, ADMIN ve todo) (HU-05).
- [x] 5.2 Detalle del turno con datos de contacto del cliente (RBAC-04).
- [x] 5.3 Acciones sobre turnos: cancelar (modal con motivo obligatorio), completar (desde `inicio`), marcar ausente (desde `fin`), con habilitación según el estado (HU-07, RN-06).
- [x] 5.4 Gestión de bloqueos: crear, listar, quitar; validación de rango y de pasado (HU-06, EC-06.4).
- [x] 5.5 Flujo de conflicto de bloqueo: lista los turnos afectados y pide confirmación con motivo antes de cancelarlos (ERR-06.1, EC-06.2).
- [x] 5.6 Métricas: turnos por período, tasa de cancelación con desglose por quién canceló, tasa de ausentismo, ocupación y top servicios (spec §5).
- [x] 5.7 Panel de auditoría de eventos (RN-08).
- [x] 5.8 Permisos: un PROFESIONAL no puede actuar sobre la agenda ajena; muestra el resultado de RBAC-02.

**Salida:** gestión completa de la agenda por el Administrador.
**Hecho cuando:** una cancelación o bloqueo hecho aquí se refleja de inmediato en la vista Cliente.

---

## Fase 6 — Integración y pulido

- [ ] 6.1 Verificar que las acciones de una vista impactan en la otra sin recargar (requisito 5).
- [ ] 6.2 Revisar el contraste, el foco por teclado, las etiquetas y los estados vacíos.
- [ ] 6.3 Revisar modo oscuro y ancho móvil (375 px).
- [ ] 6.4 Eliminar logs de depuración y código muerto; confirmar que la UI no contiene lógica de reglas.

**Salida:** prototipo estable y consistente.
**Hecho cuando:** ningún error en consola y navegación completa sin pasos rotos.

---

## Fase 7 — Verificación contra el spec

Probar en el navegador integrado y registrar el resultado observado:

- [ ] 7.1 Doble reserva: solapamiento parcial devuelve `SLOT_UNAVAILABLE` (spec §8.1, ERR-02.1).
- [x] 7.2 Concurrencia simulada: dos clientes sobre el mismo slot, solo uno se confirma (spec §8.2, EC-02.2).
- [x] 7.3 Contigüidad: 10:00–10:30 y 10:30–11:00 se aceptan (spec §8.3).
- [x] 7.4 Cancelación dentro de ventana (3 h) aceptada y slot liberado (spec §8.4).
- [x] 7.5 Cancelación a 1 h 59 min rechazada con `CANCELLATION_WINDOW_EXPIRED` (spec §8.5).
- [ ] 7.6 Contacto inválido y email sin verificar bloquean la reserva (spec §8.6, ERR-02.4, ERR-02.5).
- [ ] 7.7 Aislamiento entre clientes en "Mis turnos" (spec §8.7).
- [ ] 7.8 Bloqueo con conflicto lista los turnos y no se crea sin confirmar (spec §8.8, ERR-06.1).
- [ ] 7.9 Administrador cancela fuera de ventana con motivo y notifica al cliente (HU-07).
- [ ] 7.10 Avance del reloj: transiciones a `COMPLETADO`/`AUSENTE` y estados terminales no cancelables (ERR-07.2, ERR-07.3).
- [ ] 7.11 Doble clic en reservar no duplica turnos ni correos (ERR-02.3, EC-03.3).

**Salida:** tabla escenario ↔ resultado observado (pasa / falla).
**Hecho cuando:** todos los escenarios pasan, o las fallas están corregidas y vueltas a probar.

---

## Fase 8 — Publicación y cierre

- [x] 8.1 Publicar el Artifact con título corto, icono genérico y descripción de una oración.
- [ ] 8.2 Entregar el link y la tabla de la Fase 7.
- [x] 8.3 Listar las desviaciones o límites conocidos respecto del spec (por ejemplo, Q-01 fuera de alcance).
- [ ] 8.4 Completar la columna "Código" de la trazabilidad del spec §10.

**Salida:** link del Artifact y reporte de verificación.
**Hecho cuando:** el usuario puede abrir el prototipo y recorrer ambos flujos.

---

## Resumen de dependencias

```
F0 Preparación → F1 Dominio → F2 Estado → F3 UI compartida → F4 Cliente ┐
                                                           → F5 Admin   ┴→ F6 Integración → F7 Verificación → F8 Publicación
```

F4 y F5 pueden avanzar en paralelo una vez cerrada la Fase 3, porque ambas consumen el mismo `store` y no se tocan entre sí.

---

# Fase 2 del curso — Arquitectura desacoplada ([plan.md](plan.md) v2.0.0)

Mismo orden que [plan.md §6](plan.md). Fuente de verdad: [spec.md](spec.md) v2.0.0 (§3 INV-01 a INV-03, §4, §7, §8 y §11).

## Fase B1 — Esquema y conexión (plan §3.3)

- [x] B1.1 Seis tablas de spec §4.1 con exactamente sus campos, con el DDL de plan §3.3.1 (`backend/db.py`).
- [x] B1.2 Triggers de plan §3.3.2: solapamiento por profesional, cliente y bloqueo; profesional del servicio; transiciones y estados terminales; sin borrado de turnos; auditoría inmutable.
- [x] B1.3 `PRAGMA foreign_keys = ON`, `journal_mode = WAL`, `synchronous = FULL`, `busy_timeout = 5000` en cada conexión.
- [x] B1.4 Escrituras con `BEGIN IMMEDIATE … COMMIT` y `ROLLBACK` ante cualquier error (INV-03).

**Hecho cuando:** los tests de triggers por SQL directo y de PRAGMAs pasan.

## Fase B2 — Semilla (spec D-08)

- [x] B2.1 Mismos usuarios, servicios, horarios y bloqueos que el mock de index.html (`backend/seed.py`).
- [x] B2.2 Id UUID (spec §4) determinísticos derivados de las claves del mock (`uid("p1")`), compartidos con `prototipo-turnos.html`.
- [x] B2.3 Siembra idempotente al arrancar y `seed.py --reset` para volver a los datos de ejemplo.

## Fase B3 — Dominio (plan §3.2)

- [x] B3.1 Reglas puras en `backend/domain.py`: solapamiento `[inicio, fin)`, ventana de cancelación, contacto, grilla, antelación, horizonte, horario laboral y transiciones.
- [x] B3.2 Reloj inyectable (`backend/reloj.py`) para probar INV-01 sin esperar.
- [ ] B3.3 Reorganizar en el paquete `app/` que propone plan §3.2 (`app/main.py`, `app/dominio/…`). _(Pendiente: hoy los módulos están planos en `backend/`; el contrato y el comportamiento no cambian.)_

## Fase B4 — Contrato REST (spec §11)

- [x] B4.1 `GET /api/turnos` con RBAC por rol, filtros `estado`, `profesional_id`, `desde`, `hasta` y orden por `inicio`.
- [x] B4.2 `POST /api/turnos`: cliente para sí, ADMIN con `cliente_id`, `extra="forbid"`, `Location` en el `201`, auditoría en la misma transacción.
- [x] B4.3 `POST /api/turnos/{id}/cancelar` con campo `motivo`; INV-01 para el cliente, motivo obligatorio para profesional y admin.
- [x] B4.4 Actor por `X-Usuario-Id` con el rol leído de la base; `401 UNAUTHENTICATED` sin actor válido.
- [x] B4.5 Errores con formato `{ "error": { "codigo", "mensaje" } }` y los códigos de spec §7, incluidos `VALIDATION_ERROR` y `PERSISTENCE_UNAVAILABLE`.
- [x] B4.6 CORS solo para `http://localhost:5500` y `http://127.0.0.1:5500`, métodos `GET`/`POST`, encabezados `Content-Type` y `X-Usuario-Id`.
- [x] B4.7 Quitar los endpoints fuera del contrato v2.0.0 (catálogo, disponibilidad, usuarios, auditoría).

## Fase B5 — Verificación automática (plan §5)

- [x] B5.1 Criterios 1 a 8 aplicables de spec §8 (el 8, bloqueos, queda fuera del contrato v2.0.0).
- [x] B5.2 Criterio 9: el turno sobrevive al reinicio de la app.
- [x] B5.3 Criterio 10: si falla la auditoría, el turno no se guarda y la respuesta es `503`.
- [x] B5.4 Criterios 2 y 12: concurrencia con hilos (vía API) y con procesos (exactamente un `201`).
- [x] B5.5 Criterio 11: cancelación vía API a 1 h 59 min → `409 CANCELLATION_WINDOW_EXPIRED` y el turno sigue `CONFIRMADO`.
- [x] B5.6 Triggers por SQL directo, PRAGMAs, solo las 6 tablas de la spec y CORS permitido / no permitido.

**Hecho cuando:** `pytest` en `backend/` queda todo en verde.

## Fase B6 — Frontend `prototipo-turnos.html` (plan §3.1)

- [x] B6.1 Derivado de `index.html`, que queda sin cambios.
- [x] B6.2 Turnos con `GET /api/turnos` al iniciar, al cambiar de usuario y después de cada acción.
- [x] B6.3 Reservar y cancelar con `POST` a la API; `X-Usuario-Id` desde el selector de usuario.
- [x] B6.4 Toasts y avisos con `error.codigo` y `error.mensaje` de la respuesta.
- [x] B6.5 "Sin conexión con el servidor" sin volver a datos en memoria.
- [x] B6.6 Catálogo, horarios y bloqueos locales con los mismos id que la semilla; lo que no tiene endpoint queda en solo lectura.
- [x] B6.7 Reloj simulado reemplazado por la hora real.

## Fase B7 — Prueba de punta a punta y documentación

- [x] B7.1 Backend en `:8000` y frontend en `:5500`: reservar, recargar y reiniciar el backend (el turno sigue), cancelar, error de ventana (`409`) y aviso sin conexión.
- [x] B7.2 Reservar el mismo slot desde dos navegadores distintos (plan §5, prueba manual). _(2026-11-04: el primer cliente obtiene el turno; el segundo, con la vista sin recargar, recibe `409 SLOT_UNAVAILABLE`. En SQLite queda un solo turno y ningún solape.)_
- [x] B7.3 README con cómo correr backend, frontend y tests.
- [ ] B7.4 Completar la columna "Código" de la trazabilidad de spec §10 (requiere una versión nueva de la spec).

---

# Fase 2 del curso — Contrato ampliado ([spec.md](spec.md) v2.1.0, [plan.md](plan.md) §8)

## Fase B8 — Spec y plan v2.1.0

- [x] B8.1 spec.md v2.1.0: endpoints §11.6 – §11.13, criterios 13 a 20, D-08 resuelta, D-09 nueva, trazabilidad. §4 e INV-01 a INV-03 sin cambios.
- [x] B8.2 plan.md v2.1.0 (§8) y estas tareas.

## Fase B9 — Backend v2.1.0

- [x] B9.1 `GET /api/servicios` y `POST /api/servicios/{id}/activar` · `/desactivar` (RN-07).
- [x] B9.2 `GET` / `POST /api/horarios` con validación de franjas (F-08, D-09).
- [x] B9.3 `GET /api/disponibilidad` con los turnos de todos los clientes (F-03).
- [x] B9.4 Bloqueos: listar, crear con `conflictos` y confirmación, eliminar (RN-05).
- [x] B9.5 `POST /api/turnos/{id}/completar` y `/ausente` (RN-06).
- [x] B9.6 `GET /api/auditoria` (RN-08) y `GET /api/metricas` (F-12).
- [x] B9.7 Lecturas públicas sin `X-Usuario-Id`; `conflictos` como única extensión del error.

## Fase B10 — Verificación v2.1.0

- [x] B10.1 Criterios 8 y 13 a 20 en `backend/tests/test_v21.py`, más permisos y errores de cada endpoint.
- [x] B10.2 Atomicidad del bloqueo con cancelaciones si falla la auditoría.
- [x] B10.3 Suite completa en verde.

## Fase B11 — Frontend v2.1.0

- [x] B11.1 Servicios y disponibilidad desde la API en la Vista Cliente.
- [x] B11.2 Bloqueos (crear con conflicto y eliminar), Horarios, Servicios, Auditoría y Métricas desde la API.
- [x] B11.3 Completar y Ausente en el detalle del turno.
- [x] B11.4 Prueba de punta a punta: disponibilidad entre clientes, bloqueo con conflicto y motivo, auditoría, métricas, activar y desactivar servicio, guardar horario.
- [ ] B11.5 Probar Completar y Ausente desde la interfaz con un turno real ya iniciado (cubierto por tests; hoy la semilla no tiene turnos confirmados en curso).

# Fase 2 del curso — Revisión de `main.py` contra el contrato ([spec.md](spec.md) v2.2.0 §11 y §12, [plan.md](plan.md) §9)

Pedido: regenerar `main.py` con CORS, SQLite, tabla `turnos` y los tres endpoints de turnos. Regla: la spec es la única fuente de verdad; donde el pedido difiere, manda la spec y la diferencia queda anotada.

## Fase B12 — `main.py` según spec v2.2.0

- [x] B12.1 Contrastar el pedido con spec §4.1, §7, §11 y §12 y registrar las diferencias (tabla de abajo).
- [x] B12.2 CORS con `CORSMiddleware` y la lista explícita de `config.py` (plan §3.2: sin `*`).
- [x] B12.3 SQLite `turnos.db` con `sqlite3` nativo; el esquema de spec §4.1 (incluida la tabla `turno`) se crea al iniciar en el `lifespan` (`seed.sembrar_si_vacia` → `db`), sin SQL en `main.py` (ARQ-05).
- [x] B12.4 `GET /api/turnos` → `200` con los turnos visibles según RBAC (§11.3).
- [x] B12.5 `POST /api/turnos` → Pydantic con `extra="forbid"`; INV-02 en el servidor → `409 SLOT_UNAVAILABLE`; `201` con `Location` (§11.4).
- [x] B12.6 `POST /api/turnos/{id}/cancelar` → INV-01 con el reloj del servidor → `409 CANCELLATION_WINDOW_EXPIRED` a menos de 2 h; `200` con `estado = CANCELADO` (§11.5).
- [x] B12.7 Docstring de `main.py` con el arranque `--reload` y la URL de Swagger UI; versión de la app alineada con la spec (2.2.0).
- [x] B12.8 Suite completa en verde y comprobaciones ARQ de plan §9.3 sin cambios.

### Diferencias entre el pedido y la spec (manda la spec)

| Pedido | Spec v2.2.0 | Motivo |
|---|---|---|
| `allow_origins=["*"]` | Solo `http://localhost:5500` y `http://127.0.0.1:5500` | plan §3.2 y test de CORS no permitido (plan §5) |
| Tabla `turnos` con `cliente_nombre`, `cliente_email`, `servicio`, `fecha_hora`, `estado` | Tabla `turno` con `cliente_id`, `profesional_id`, `servicio_id`, `inicio`, `fin`, `estado`, `motivo_cancelacion`, `cancelado_por_id`, `creado_en`, `actualizado_en` | §4.1 y §11.2: el contacto vive en `Usuario` (RN-03) y el turno referencia por UUID |
| Código `HORARIO_NO_DISPONIBLE` | `SLOT_UNAVAILABLE` (409) | Catálogo §7 |
| Código `CANCELACION_FUERA_DE_VENTANA` | `CANCELLATION_WINDOW_EXPIRED` (409) | Catálogo §7 |
| Estado `CANCELADO_CLIENTE` | `CANCELADO`, con `cancelado_por_id` = actor | RN-06 y §11.5 |
| `main.py` crea la tabla y consulta SQLite | `main.py` solo abre la conexión; el SQL vive en `service.py` y `db.py` | §12.3 ARQ-05 |
| `GET /api/turnos` devuelve todos los turnos | Turnos visibles según el rol del `X-Usuario-Id` | §11.3, RBAC-01 |

Si se quiere el modelo del pedido, primero hay que cambiar spec §4.1, §7 y §11 (nueva versión) y después el código.

# Preparación de la Clase 5 — Aislamiento del repositorio y entorno de pruebas

Pedido: dejar el repositorio y el entorno listos para los tests automatizados. No cambia el contrato de spec §11 ni la arquitectura de §12.

## Fase B13 — Dependencias, entorno y arranque

- [x] B13.1 `backend/requirements.txt` con las dependencias de ejecución (`fastapi`, `uvicorn`, `pydantic`) y de pruebas (`pytest`, `httpx2`), en versiones fijas. _(Hecho con variación: el pedido nombraba `httpx`; se usa `httpx2` porque `starlette.testclient` marca `httpx` como deprecado. `fastapi` 0.163.1 y `pydantic` 2.14.3.)_
- [x] B13.2 `.gitignore` de Python: entornos virtuales, `__pycache__/`, `.pytest_cache/`, cobertura, base SQLite, `.env` y archivos del sistema operativo y de IDEs.
- [x] B13.3 `backend/.venv` recreado desde cero solo con `requirements.txt`; `pip check` sin conflictos y nada instalado en el Python global.
- [x] B13.4 `GET /` redirige (307) a `/docs`, con `include_in_schema=False`: no figura en el contrato ni en OpenAPI.
- [x] B13.5 `iniciar.py` en la raíz: levanta backend (8000, `--reload`) y frontend (5500, solo `127.0.0.1`) como procesos separados con el Python del venv; verifica puertos libres y Ctrl+C cierra ambos con sus hijos. Atajo documentado en el README.
- [x] B13.6 Suite completa en verde con el entorno nuevo: 140 pruebas, sin advertencias de deprecación.
- [x] B13.7 Arranque y cierre con Ctrl+C verificados desde la terminal del usuario: puertos 8000 y 5500 libres, sin procesos huérfanos.

## Fase B14 — Matriz de tests automatizados ([spec.md](spec.md) v2.3.0 §13)

- [x] B14.1 `backend/tests/test_turnos.py` con base SQLite aislada: plantilla sembrada una vez por módulo y copia propia por test; `config.DB_PATH` apunta a la copia y el `TestClient` no ejecuta el `lifespan` (TST-01).
- [x] B14.2 Guarda de `backend/turnos.db`: huella SHA-256 antes y después del módulo (TST-01).
- [x] B14.3 Test 1 — reserva válida para mañana: `201`, visible en `GET /api/turnos` desde otro cliente HTTP y escrita en el archivo (INV-03).
- [x] B14.4 Test 2 — mismo horario y profesional: `409 SLOT_UNAVAILABLE`, sin persistir nada (INV-02).
- [x] B14.5 Test 3 — cancelación a 5 h: `200 CANCELADO` (INV-01).
- [x] B14.6 Test 4 — cancelación a 45 min: `409 CANCELLATION_WINDOW_EXPIRED` y el turno sigue `CONFIRMADO` (INV-01). _(Hecho con variación: RN-04 impide crear un turno a 45 min; se crea a 5 h y se adelanta el reloj.)_
- [x] B14.7 Test 5 — cuerpo inválido en 5 variantes: `422 VALIDATION_ERROR`, sin persistir nada. _(Hecho con variación: el pedido aceptaba 400; la spec fija 422.)_
- [x] B14.8 Módulo en 1,16 s según pytest (TST-03); suite completa en verde: 149 pruebas.
- [x] B14.9 spec.md v2.3.0: §13 Matriz de Tests Automatizados y entrada en el historial de cambios.

## Fase B15 — Blindaje de endpoints y refactorización de legibilidad ([spec.md](spec.md) v2.3.1)

Estado de los hitos de la Clase 5: entorno virtual ✅ (B13.1 a B13.3), suite de testing ✅ (B14 y B15.1 a B15.4), refactorización de legibilidad del backend ✅ (B15.5 a B15.7). La reorganización en el paquete `app/` (B3.3) es otra tarea y sigue pendiente.

- [x] B15.1 Sondeo previo de los 3 casos de borde: el backend ya respondía según spec §11.4 y §11.5, así que no hizo falta cambiar la lógica, solo protegerla con tests.
- [x] B15.2 Test 6 — `servicio_id`, `inicio` o `cliente_id` vacíos o solo con espacios: `422 VALIDATION_ERROR`, sin persistir nada.
- [x] B15.3 Test 7 — cancelar un turno inexistente (UUID válido o id arbitrario, como cliente o admin): `404 NOT_FOUND`.
- [x] B15.4 Test 8 — cancelar dos veces: `409 INVALID_STATE_TRANSITION` y el turno no cambia (RN-06). _(Hecho con variación: el pedido aceptaba 400 o 409; la spec fija 409.)_
- [x] B15.5 `main.py`: rutas agrupadas por etiqueta (turnos, catálogo, agenda), `summary` y descripción en cada ruta, descripción general de la API y de las etiquetas en Swagger, encabezado `X-Usuario-Id` documentado, nombres más claros en manejadores de errores y dependencias (`respuesta_de_error`, `manejar_*`, `abrir_conexion`, `actor_obligatorio`).
- [x] B15.6 `schemas.py`: descripción de los campos de entrada y de los modelos; cada status de error en Swagger indica qué códigos de la §7 agrupa.
- [x] B15.7 Contrato sin cambios: comparación automática del OpenAPI antes y después (16 operaciones con las mismas rutas, métodos, parámetros, cuerpos, status y modelos).
- [x] B15.8 Módulo `test_turnos.py` con 18 casos en 1,67 s (TST-03); suite completa en verde: 158 pruebas, sin advertencias de deprecación.
- [x] B15.9 spec.md v2.3.1: escenarios 6 a 8 en la §13 y entrada en el historial de cambios. Versión de la app en Swagger alineada (2.3.1).

## Fase B16 — Integración frontend ↔ backend ([spec.md](spec.md) v2.3.2 §13.4)

- [x] B16.1 Prueba en vivo con `iniciar.py` sobre una base temporal (`TURNOS_DB`): las 16 operaciones que usa `prototipo-turnos.html` responden por HTTP real, con preflight CORS desde `:5500`. `backend/turnos.db` no se tocó.
- [x] B16.2 `backend/tests/test_integracion_frontend.py`: lee el HTML y lo compara con `app.openapi()` (I-1 a I-6): `API_BASE` y CORS, rutas del objeto `Api` contra el contrato, parámetros y claves de los cuerpos, UUID, usuarios y `CONFIG` contra `seed.py` y `config.py`, preflight de cada llamada y pedidos con los cuerpos exactos del navegador.
- [x] B16.3 Validación de los tests con roturas de ejemplo (ruta, clave del cuerpo, parámetro, UUID, ventana de 2 h, CORS sin `X-Usuario-Id`): cada una hace fallar el test que corresponde.
- [x] B16.4 39 casos en 1,1 s; suite completa en verde: 197 pruebas, sin advertencias de deprecación.
- [ ] B16.5 Prueba en un navegador real (renderizado de React, flujos de la UI): queda manual; los tests cubren el contrato entre capas, no la interfaz.

## Pendientes fuera de v2.1.0

- [ ] Endpoint de usuarios (hoy la lista sigue local en el frontend).
- [ ] Login real y verificación de email (F-01, D-06) y emails (F-13, D-07): requieren cambiar la §4.
- [ ] Alta y edición de servicios (F-07).
- [ ] Reorganizar el backend en el paquete `app/` (plan §7, decisión 7).
