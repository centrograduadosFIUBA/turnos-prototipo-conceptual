# plan.md — Plan técnico v2: arquitectura desacoplada (Fase 2)

| Campo | Valor |
|---|---|
| Versión | 2.0 (la v1 es el plan del prototipo de la Fase 1, conservado en el Anexo A) |
| Base normativa | [spec.md](spec.md) v0.2.0 (INV-01, INV-02, INV-03, §11 contrato REST, §12 abstención) |
| Fecha | 2026-10-27 |
| Estado | Pendiente de aprobación |

> Fuentes de la verdad: `spec.md`, este `plan.md` e `index.html`. Ningún elemento del plan puede contradecir el spec; ante un hueco, se corrige primero el spec.

## 1. Objetivo de la Fase 2

Pasar del prototipo monolítico en memoria (`index.html`) a software real con tres capas desacopladas, de modo que los turnos persistan (INV-03) y las reglas INV-01 e INV-02 las haga cumplir el servidor, no la pantalla.

## 2. Arquitectura de 3 capas

```
┌──────────────────────────┐   HTTP + JSON    ┌───────────────────────────┐   SQL    ┌────────────────┐
│ Capa 1 · Frontend        │ ───────────────▶ │ Capa 2 · Backend          │ ───────▶ │ Capa 3 · BD    │
│ prototipo-turnos.html    │ ◀─────────────── │ Python + FastAPI :8000    │ ◀─────── │ SQLite         │
│ (sin estado de dominio)  │   fetch /api/*   │ CORS habilitado           │          │ turnos.db      │
└──────────────────────────┘                  └───────────────────────────┘          └────────────────┘
```

| Capa | Tecnología | Responsabilidad | Lo que NO hace |
|---|---|---|---|
| 1. Frontend | `prototipo-turnos.html` (derivado de `index.html`; React + Tailwind por CDN) | Mostrar datos y capturar acciones. Consume JSON con `fetch` contra `http://localhost:8000` | No decide reglas ni guarda turnos; solo muestra el error que devuelve la API |
| 2. Backend | Python con FastAPI, puerto **8000**, `CORSMiddleware` habilitado para el origen del frontend | Exponer el contrato REST de spec §11; validar y aplicar INV-01, INV-02, RN-03, RN-04 y RN-06; calcular `fin` | No guarda estado de dominio en memoria del proceso |
| 3. Persistencia | SQLite en el archivo `turnos.db` | Guardar los datos de forma atómica y durable (INV-03) | No contiene lógica de presentación |

### 2.1 Contrato entre capas

Es el de spec §11, sin agregados:

| Método y ruta | Regla que hace cumplir |
|---|---|
| `GET /api/turnos` | INV-03 (lee de la base) |
| `POST /api/turnos` | INV-02, RN-03, RN-04, INV-03 |
| `POST /api/turnos/{id}/cancelar` | INV-01, RN-06, INV-03 |

Los errores se devuelven con los códigos del catálogo de spec §7.

### 2.2 Persistencia y atomicidad

- Las escrituras usan una transacción de escritura exclusiva (`BEGIN IMMEDIATE`): se verifica el solapamiento y se inserta dentro de la misma transacción. Así, dos reservas simultáneas por el mismo horario no pueden confirmarse ambas (INV-02 + INV-03).
- Los instantes se guardan en UTC (RN-04).
- No hay `DELETE` sobre turnos (RN-06): cancelar cambia el estado.

### 2.3 Esquema de `turnos.db` (grounding estricto)

Solo lo que figura en la §4 del spec; no se agrega ninguna tabla ni columna.

| Tabla | Columnas (idénticas a spec §4.1) |
|---|---|
| `usuario` | `id`, `email`, `email_verificado`, `password_hash`, `nombre_completo`, `telefono`, `rol`, `activo`, `creado_en` |
| `servicio` | `id`, `profesional_id`, `nombre`, `descripcion`, `duracion_min`, `precio_referencia`, `activo` |
| `turno` | `id`, `cliente_id`, `profesional_id`, `servicio_id`, `inicio`, `fin`, `estado`, `motivo_cancelacion`, `cancelado_por_id`, `creado_en`, `actualizado_en` |

`HorarioLaboral`, `Bloqueo` y `AuditoriaEvento` existen en el spec pero quedan **fuera** de esta fase; se incorporan solo con su propia tarea y las columnas ya definidas. Cualquier campo no listado en la §4 requiere antes un cambio de spec (§12).

## 3. Por qué el desacoplamiento: la memoria volátil de JS viola la integridad

El prototipo guarda todo en un `useReducer` dentro de la página. Eso es válido para una maqueta, pero incumple el contrato del sistema:

1. **Sin persistencia (INV-03).** Al recargar o cerrar la pestaña, los turnos desaparecen. Una reserva confirmada no puede perderse por reiniciar el navegador.
2. **Sin fuente única de verdad.** Cada navegador tiene su propia copia. Dos clientes pueden reservar el mismo horario en pantallas distintas y ambos ver "confirmado", violando INV-02. La concurrencia del prototipo está simulada dentro de un único proceso.
3. **Reglas bajo control del cliente.** El código vive en el navegador, y quien lo abre puede modificarlo (por ejemplo, alterar el reloj o saltarse INV-01). Contradice RBAC-01: la UI nunca es la barrera de seguridad.
4. **Sin atomicidad.** No hay transacciones: un fallo a mitad de operación deja el estado inconsistente.
5. **Sin trazabilidad durable (RN-08).** Un log que se pierde al recargar no sirve como auditoría.

Separar la presentación (Capa 1) de las reglas (Capa 2) y del almacenamiento (Capa 3) permite que cada una se pruebe, reemplace y escale por separado (por ejemplo, SQLite por PostgreSQL, según D-04) sin tocar las otras.

## 4. Fases de trabajo propuestas

| Fase | Entregable | Criterio de cierre |
|---|---|---|
| 2.0 | Spec v0.2.0 y plan v2 aprobados | Revisión humana |
| 2.1 | Esquema SQLite según §2.3 y datos semilla basados en los mock de `index.html` | Tablas creadas sin campos fuera del spec |
| 2.2 | Backend FastAPI con los 3 endpoints, CORS y reglas INV-01/INV-02 | Criterios de aceptación 1 a 5 y 11 del spec pasan contra la API |
| 2.3 | `prototipo-turnos.html` consumiendo la API | La vista Cliente reserva y cancela vía HTTP |
| 2.4 | Verificación de INV-03 | Criterios 9 y 10: reiniciar el backend conserva los turnos |

## 5. Riesgos y puntos abiertos

- **Autenticación:** F-01 no existe todavía, así que el actor se identifica provisoriamente en el cuerpo de la petición (spec D-06). Es una brecha de seguridad conocida y temporal.
- **SQLite vs. PostgreSQL:** SQLite no tiene restricción de exclusión de rangos; la garantía de INV-02 depende de la transacción exclusiva (spec D-04).
- **Nombre del frontend:** se pide `prototipo-turnos.html`; el prototipo actual es `index.html`. El plan asume una copia adaptada, y `index.html` queda como referencia de la Fase 1.
- **Vista Administrador:** sus acciones (bloqueos, completar, métricas) no están en el contrato de la Fase 2; esas funciones quedan sin backend hasta ampliar el spec.

---

# Anexo A — Plan v1 (Fase 1, prototipo en memoria)

> Se conserva sin cambios de fondo como historial. Describe `index.html`.

## A.1 Formato de entrega

- Un único archivo HTML publicado como Artifact. Dentro va un solo componente React con Tailwind (`cdn.tailwindcss.com`) y Lucide Icons.
- React, Babel y Lucide se cargan desde CDN con versión fija. No hay build ni dependencias locales.
- Antes de escribirlo se carga la guía de diseño de Artifacts: tokens de color, modo oscuro y layout responsive.
- El componente es modular dentro del mismo archivo, con una sección lógica por responsabilidad:

| Módulo | Contenido |
|---|---|
| `domain/` | Funciones puras del spec: solapamiento, ventana de cancelación, validación de contacto, cálculo de slots, transiciones de estado |
| `store` | Estado único con `useReducer` y un `Context`; un reducer centralizado donde se aplican todas las reglas |
| `ClientView` | Servicio, grilla de slots, formulario, "Mis turnos" |
| `AdminView` | Agenda, métricas, bloqueos, acciones sobre turnos |
| `ui/` | Componentes compartidos: toasts, modales, badges de estado, barra superior |

## A.2. Decisión de diseño clave

Toda regla vive en `domain/` y el reducer la ejecuta. La UI nunca decide si algo está permitido: solo muestra el error que devuelve el dominio, con los mismos códigos del spec (`SLOT_UNAVAILABLE`, `CANCELLATION_WINDOW_EXPIRED`, etc.). Esto simula el principio RBAC-01 de que la UI no es la barrera de seguridad.

## A.3. Reglas que se implementan

- **RN-01:** cancelación del cliente bloqueada a menos de 2 h del inicio. El Administrador la salta, pero con motivo obligatorio.
- **RN-02:** sin solapamiento con intervalos `[inicio, fin)`, contigüidad válida, y sin solapar con bloqueos ni con turnos propios del cliente.
- **RN-03:** nombre, email y teléfono válidos y email verificado antes de reservar.
- **RN-04:** grilla de 15 min, antelación mínima de 1 h, horizonte de 60 días, y `fin` calculado por el sistema.
- **RN-05:** bloquear un rango con turnos activos lista los conflictos y exige confirmar la cancelación.
- **RN-06:** estados terminales, sin borrado físico.
- **RN-08:** panel de auditoría visible para el Administrador.
- **RBAC:** el cliente solo ve sus turnos. Con el cambio de rol se ve en vivo qué aparece y qué desaparece.

## A.4. Datos mock en memoria

- 3 profesionales, 5 a 6 servicios con duraciones distintas (30, 45, 60 min).
- 2 clientes. Uno de ellos tiene el email sin verificar, para poder probar `EMAIL_NOT_VERIFIED`.
- Unos 12 turnos distribuidos en los próximos días: confirmados, cancelados, completados y ausentes. Incluye uno que empieza dentro de 1 h 59 min y otro a las 3 h, para probar RN-01 sin esperar.
- 1 o 2 bloqueos y horario laboral de lunes a viernes.
- Las fechas son relativas a "hoy" real, así que el prototipo no envejece.
- Una sola fuente de datos alimenta ambas vistas, así que cualquier acción en una se refleja de inmediato en la otra.

## A.5. Vistas

- **Barra superior:** el selector Cliente/Administrador, el usuario activo (con selector entre los 2 clientes mock) y un reloj simulado con botones para avanzar tiempo (+1 h, +1 día). El reloj sirve para auditar RN-01 y los estados `COMPLETADO`/`AUSENTE`.
- **Cliente:**
  - Elige servicio, profesional y fecha.
  - Ve la grilla de slots y un modal de confirmación con los datos de contacto.
  - Ve "Mis turnos", con el botón de cancelar deshabilitado y con tooltip explicativo dentro de las 2 h.
- **Administrador:**
  - Vista de agenda día/semana y vista de lista.
  - Métricas: turnos por período, tasas de cancelación y ausentismo, ocupación y top servicios.
  - Acciones sobre turnos: cancelar con motivo, completar y marcar ausente.
  - Gestión de bloqueos.
  - Un filtro de profesional para el rol `ADMIN`.

## A.6. Verificación

- Probar en el navegador integrado los 8 escenarios de aceptación del spec §8, incluyendo el doble clic y la reserva del mismo slot desde dos clientes (concurrencia simulada en el reducer).
- Revisar la consola, el ancho móvil y el modo oscuro antes de publicar.
- Entregar el link del Artifact y una tabla que cruza cada escenario con el resultado observado.

## A.7. Decisiones tomadas (por defecto, salvo indicación contraria)

| # | Tema | Decisión |
|---|---|---|
| 1 | Reloj simulado con botones para avanzar tiempo | **Sí** |
| 2 | Selector "Profesional / ADMIN" en la vista Administrador | **Sí** |
| 3 | Emails como "bandeja simulada" (F-13) | **Sí**, panel lateral colapsable |
| 4 | Reducir el horario laboral con turnos reservados (Q-01) | **Fuera** del prototipo; solo se implementa el bloqueo (RN-05) |
| 5 | Persistencia entre recargas | **No**: todo en memoria, con botón "Reiniciar datos" |
