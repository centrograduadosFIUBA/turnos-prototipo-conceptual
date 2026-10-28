# tareas.md — Tareas por fase para ejecutar [plan.md](plan.md)

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
---

# Bloque B — Fase 2 del curso: backend desacoplado (plan.md v2)

> Las fases 0 a 8 de arriba corresponden al prototipo en memoria (Fase 1 del curso). Este bloque ejecuta [plan.md](plan.md) v2 sobre [spec.md](spec.md) v0.2.1. Fuente de verdad: el spec (esquema de la §4, errores de la §7, contrato de la §11).

## Fase B1 — Esquema y semilla (SQLite)

- [x] B1.1 Tablas `usuario`, `servicio` y `turno` con las columnas exactas de la §4.1, creadas automáticamente al iniciar el servidor.
- [x] B1.2 Datos semilla (solo si la base está vacía): 7 usuarios, 6 servicios tomados de `index.html`. Sin turnos: los crea la API.
- [x] B1.3 `password_hash` con marcador no utilizable, porque F-01 (login) no está en esta fase (D-06).

## Fase B2 — Backend FastAPI (`main.py`)

- [x] B2.1 FastAPI con CORS permisivo (`allow_origins=["*"]`).
- [x] B2.2 `GET /api/turnos` con filtros opcionales (spec §11.1).
- [x] B2.3 `POST /api/turnos`: valida con Pydantic; aplica INV-02 (profesional y cliente), RN-03 y RN-04 dentro de `BEGIN IMMEDIATE`; `fin` y `profesional_id` calculados (spec §11.2).
- [x] B2.4 `POST /api/turnos/{id}/cancelar`: aplica INV-01 y RN-06; exige motivo si cancela PROFESIONAL/ADMIN; 404 para turno ajeno de un CLIENTE (spec §11.3, RBAC-02).
- [x] B2.5 Errores con cuerpo `{"error": CODIGO, "detalle": texto}` usando el catálogo de la §7.
- [ ] B2.6 Revisión humana de `main.py` contra el spec.

**Fuera de esta fase (documentado):** horario laboral (RN-04 parcial), bloqueos (RN-05), auditoría (RN-08), emails (F-13) y vista Administrador; ver spec §9 y plan §5.

## Fase B3 — Verificación

- [ ] B3.1 Criterios 1, 2, 3 del spec §8 contra la API (doble reserva, concurrencia, contigüidad).
- [ ] B3.2 Criterios 4, 5, 11 (cancelación en ventana, a 1 h 59 min, contrato REST).
- [ ] B3.3 Criterio 9: reiniciar el servidor conserva los turnos (INV-03).
- [ ] B3.4 Probar en Swagger UI (`/docs`).

## Fase B4 — Frontend conectado

- [ ] B4.1 `prototipo-turnos.html` consume la API con `fetch` (plan §2).
- [ ] B4.2 Pendiente: endpoints de la vista Administrador (requiere ampliar el spec).
