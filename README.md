# Turnos Pro — Gestión de turnos y reservas de servicios profesionales

Este proyecto forma parte del curso **"Creá tu proyecto con Inteligencia Artificial"**. Es el resultado de las **3 primeras clases, que conforman la FASE 1** del curso: pasar de una idea a un prototipo funcional trabajando con la metodología **Spec-Driven Development (SDD)**, donde primero se escribe una especificación formal y recién después se genera el código.

- **Prototipo en línea:** https://claude.ai/artifact/JUv3cgvTQv1i2vxf3DK5z2 
- **Prototipo local:** abrí [index.html](index.html) con doble clic. Necesita internet, porque React y Tailwind se cargan desde CDN.
- **Fase 2 (software real):** [prototipo-turnos.html](prototipo-turnos.html) + backend FastAPI + SQLite. Ver [Cómo correr la Fase 2](#cómo-correr-la-fase-2).

## Cómo clonar este repositorio

Para descargar el proyecto directamente desde GitHub, abrí una terminal y ejecutá:

```bash
git clone https://github.com/centrograduadosFIUBA/turnos-prototipo-conceptual.git
cd turnos-prototipo-conceptual
```

Después, abrí `index.html` en el navegador. No hace falta instalar dependencias ni compilar el proyecto.

## Cómo hacer un fork y clonarlo

Un fork crea una copia del repositorio en tu propia cuenta de GitHub. Es útil si querés experimentar o proponer cambios sin modificar directamente el repositorio original.

1. Iniciá sesión en [GitHub](https://github.com/) y abrí el [repositorio del proyecto](https://github.com/centrograduadosFIUBA/turnos-prototipo-conceptual).
2. Presioná **Fork** en la parte superior derecha.
3. Elegí tu cuenta como destino y confirmá la creación del fork.
4. En una terminal, reemplazá `<tu-usuario>` por tu nombre de usuario de GitHub y cloná tu fork:

   ```bash
   git clone https://github.com/<tu-usuario>/turnos-prototipo-conceptual.git
   cd turnos-prototipo-conceptual
   ```

5. Si querés mantener tu copia al día con el repositorio original, agregalo como remoto `upstream`:

   ```bash
   git remote add upstream https://github.com/centrograduadosFIUBA/turnos-prototipo-conceptual.git
   git remote -v
   ```

## Qué es

Una aplicación web para reservar turnos con profesionales. Tiene dos vistas sobre los mismos datos en memoria:

- **Vista Cliente:** elegir servicio, ver horarios libres, reservar, confirmar y cancelar turnos propios.
- **Vista Administrador:** agenda, métricas, bloqueos de horarios, servicios, auditoría y acciones sobre los turnos.

Las reglas del negocio (sin doble reserva, cancelación hasta 2 horas antes, datos de contacto válidos, permisos por rol) están implementadas tal como las define el spec. La pantalla no decide qué está permitido: cada acción pasa por un módulo de dominio que responde con códigos de error como `SLOT_UNAVAILABLE`.

## Archivos del proyecto

| Archivo | Contenido |
|---|---|
| [spec.md](spec.md) | Especificación técnica: alcance del MVP, roles y permisos, reglas invariantes y modelo de datos |
| [historias-de-usuario.md](historias-de-usuario.md) | 7 historias de los dos flujos principales, con criterios en Gherkin y casos borde |
| [plan.md](plan.md) | Plan para convertir la especificación en un prototipo interactivo |
| [tareas.md](tareas.md) | Tareas organizadas en 9 fases para ejecutar el plan |
| [index.html](index.html) | Fase 1: la aplicación completa en un solo archivo (dominio, estado, vistas y datos de ejemplo). Se conserva sin cambios |
| [guia-de-uso.md](guia-de-uso.md) | Funcionalidades y guía paso a paso de pruebas en la interfaz (Fase 1) |
| [prototipo-turnos.html](prototipo-turnos.html) | Fase 2, capa 1: el frontend derivado de index.html que consume la API REST |
| [backend/](backend/) | Fase 2, capas 2 y 3: API FastAPI (`main.py`), casos de uso (`service.py`), reglas puras (`domain.py`), SQLite (`db.py`), semilla (`seed.py`) y tests (`tests/`) |

## Cómo se construyó: paso a paso

El flujo fue siempre el mismo: **pedir un documento, revisarlo, y usarlo como base del siguiente paso**. Cada paso produjo un archivo que alimentó al siguiente.

```
Spec  →  Historias de usuario  →  Plan  →  Tareas  →  Código (index.html)  →  Publicación y guía  →  README
```

### Paso 1 — Especificación técnica (`spec.md`)

Se le pidió a la IA que actuara como arquitecto de software y definiera, antes de escribir código, el contrato del sistema: qué entra en el MVP, quién puede hacer qué, qué reglas no se pueden romper y cómo se relacionan los datos.

**Prompt:**

```
Actuá como un Arquitecto de Software y Analista de Sistemas Senior bajo la metodología Spec-Driven Development (SDD).

Quiero diseñar una aplicación web para la gestión de turnos y reservas de servicios profesionales. Antes de escribir una sola línea de código, vamos a construir la especificación técnica formal (nuestro spec.md como contrato del sistema).

Generá un documento técnico estructurado en Markdown que contenga:
1. Alcance del MVP: Qué incluye explícitamente y qué queda fuera de esta primera versión.
2. Matriz de Roles y Permisos (RBAC):
   - Cliente (exploración, reserva de turnos, consulta y cancelación de sus propias citas).
   - Profesional / Administrador (gestión de agenda, bloqueo de rangos horarios, visualización de métricas).
3. Reglas Invariantes del Negocio (restricciones no negociables):
   - Ventana de cancelación mínima permitida (ej: 2 horas antes).
   - Prohibición estricta de doble reserva / solapamiento sobre un mismo horario.
   - Validación obligatoria de datos de contacto.
4. Modelo de Datos Conceptual: Entidades principales (Usuarios, Servicios, Turnos) y sus relaciones.
```

**Resultado:** [spec.md](spec.md), con funcionalidades numeradas (F-01 a F-13), reglas de negocio (RN-01 a RN-08), una matriz de permisos, un diagrama de entidades, un catálogo de errores y criterios de aceptación.

### Paso 2 — Historias de usuario (`historias-de-usuario.md`)

Con el spec como base, se derivaron las historias de los dos flujos más importantes, cada una con criterios en formato Gherkin y casos borde para prevenir.

**Prompt:**

```
Tomando como base estricta el spec.md que acabamos de definir, generá las Historias de Usuario críticas para este MVP.

Para cada historia de usuario:
1. Formato estándar: "Como [rol], quiero [acción], para [beneficio]".
2. Criterios de Aceptación obligatorios en formato Gherkin (Dado que... / Cuando... / Entonces...).
3. Identificación de al menos un caso borde (Edge Case) o manejo de error a prevenir.

Enfocate en los dos flujos core:
- Flujo 1: Reserva y confirmación de turno por parte del Cliente.
- Flujo 2: Gestión de agenda y cancelación de turno por parte del Administrador.
```

**Resultado:** [historias-de-usuario.md](historias-de-usuario.md). Al derivar las historias aparecieron cinco huecos del spec, que quedaron listados como preguntas abiertas.

### Paso 3 — Plan de implementación (revisión antes de construir)

El prompt pedía explícitamente compartir un plan **antes de empezar**, para poder revisarlo. La IA no escribió código en este paso: presentó el plan, los datos de ejemplo previstos y cinco decisiones con un valor por defecto.

**Prompt:**

```
Ahora vamos a "compilar" nuestra especificación técnica en un prototipo interactivo funcional utilizando Claude Artifacts (un único componente React con Tailwind CSS y Lucide Icons).

Requisitos de implementación:
1. Fuente de la verdad: Implementá estrictamente las reglas invariantes, roles y criterios de aceptación definidos en nuestro spec.md.
2. Selector de Rol en la barra superior: Permitir alternar entre "Vista Cliente" y "Vista Administrador" para auditar permisos en vivo.
3. Vista Cliente: Selector de servicio, grilla de horarios disponibles, formulario de confirmación y vista de turnos agendados con opción de cancelar (respetando la regla de tiempo límite).
4. Vista Administrador: Calendario/lista de turnos, métricas básicas, acción de cancelar/completar turnos y bloqueo de horarios.
5. Estado y datos mock: Incluí datos iniciales realistas en memoria para que las acciones en una vista impacten de inmediato en la otra.

Generá el componente interactivo completo, modular y listo para ejecutar.

Antes de comenzar, comparte un plan de los pasos que seguirás para que pueda revisarlo.
```

### Paso 4 — Guardar el plan y organizarlo en tareas (`plan.md`, `tareas.md`)

Se aprobó el plan y se pidió dejarlo por escrito, más una lista de tareas por fases.

**Prompt:**

```
guarda el plan en el archivo plan.md y luego genera un archivo tareas.md organizado en fases para cumplir ese plan
```

**Resultado:** [plan.md](plan.md) y [tareas.md](tareas.md), este último con 9 fases (preparación, dominio, estado, interfaz compartida, vista Cliente, vista Administrador, integración, verificación y publicación), cada una con su criterio de cierre.

### Paso 5 — Construcción del prototipo (`index.html`)

Se pidió llevar todo a un único archivo funcional. La IA lo escribió, lo abrió en el navegador integrado y verificó el comportamiento: ejecutó unas 38 comprobaciones de las reglas del spec, entre ellas dos clientes sobre el mismo horario, el límite exacto de 2 horas y los bloqueos con conflicto. También corrigió un detalle visual de capitalización en las fechas.

**Prompt:**

```
quiero llegar a tener el index.html funcional con todo el codigo alli de manera monolitica
```

**Resultado:** [index.html](index.html). Incluye herramientas para auditar el comportamiento: reloj simulado, bandeja de emails simulada, "Modo auditoría" y simulaciones de concurrencia y doble clic.

### Paso 6 — Publicación y guía de uso (`guia-de-uso.md`)

Se publicó el prototipo como Artifact de Claude y se documentaron las funcionalidades con una guía de pruebas paso a paso.

**Prompt:**

```
publica el artifact y agrega a la carpeta una documentacion completa de las funcionalidaes y de las preubas que se pueden hacer en la interface. una guia paso a paso
```

**Resultado:** el [Artifact publicado](https://claude.ai/artifact/JUv3cgvTQv1i2vxf3DK5z2) y [guia-de-uso.md](guia-de-uso.md), con más de 25 pruebas organizadas por bloque.

### Paso 7 — Este README

**Prompt:**

```
Genera un readme explicando que este codigo forma parte del curso "Creá tu proyecto con Inteligencia Artificial" y es el resultado de las 3 primeras Clases que conforman la FASE 1 del curso. Agrega en ese readme el paso a paso que hicmos en esta charla y los prompts que fuimos usando en cada caso
```

## Qué se aprende con este recorrido

1. **La especificación va primero.** Con el spec escrito, el resto de los documentos y el código se derivan de él y se pueden contrastar contra él.
2. **Pedir el plan antes del código** permite corregir el rumbo sin gastar trabajo de construcción.
3. **Cada documento alimenta al siguiente.** El spec generó las historias, las historias y el spec generaron el plan, y el plan generó las tareas y el código.
4. **Un prototipo se verifica contra el spec**, no contra la intuición. Cada regla tiene un escenario de prueba asociado.
5. **Revisar lo que produce la IA importa.** Al derivar las historias se detectaron huecos del spec, y al probar el código se corrigieron detalles.

## Cómo probarlo

Abrí [index.html](index.html) y seguí [guia-de-uso.md](guia-de-uso.md). Tres pruebas para empezar:

1. **Reserva:** Vista Cliente, usuaria Lucía, elegí un servicio y un horario libre, y confirmá. Después mirá la Vista Administrador: el turno ya está en la agenda.
2. **Regla de las 2 horas:** pulsá `+1 min` en el reloj simulado y probá cancelar el turno de las 09:30. Con **Modo auditoría** activado, el dominio lo rechaza con `CANCELLATION_WINDOW_EXPIRED`.
3. **Doble reserva:** en el modal de reserva, activá la simulación de otro cliente en el mismo instante. Queda un solo turno.

## Cómo correr la Fase 2

La Fase 2 separa el sistema en tres capas ([plan.md §3](plan.md)): el navegador solo presenta, el backend decide y la base de datos recuerda. Los turnos se guardan en `backend/turnos.db` y sobreviven a recargar la página y a reiniciar el servidor (INV-03).

Necesitás **Python 3.11 o superior**.

**Atajo — los dos servidores con un solo comando.** Con el entorno ya creado (paso de la Terminal 1), desde la raíz del proyecto:

```bash
python iniciar.py            # agregá --abrir para que abra la app en el navegador
```

Levanta el backend (8000, con `--reload`) y el frontend (5500) como procesos separados, usando siempre el Python de `backend/.venv`. Ctrl+C detiene ambos. Si alguno de los puertos ya está en uso, avisa y no arranca nada.

Para hacerlo a mano, abrí dos terminales en la carpeta del proyecto.

**Terminal 1 — Backend (puerto 8000).** La primera vez, creá el entorno e instalá las dependencias:

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

(En macOS o Linux, usá `.venv/bin/python` en lugar de `.venv/Scripts/python`.)

Después, cada vez que quieras usarlo:

```bash
cd backend
.venv/Scripts/python -m uvicorn main:app --port 8000
```

Al arrancar crea `turnos.db` con el esquema de [plan.md §3.3](plan.md) y la carga con los datos de ejemplo si está vacía. La documentación interactiva de la API queda en http://localhost:8000/docs.

**Terminal 2 — Frontend (puerto 5500):**

```bash
python -m http.server 5500
```

Abrí http://localhost:5500/prototipo-turnos.html. No lo abras con doble clic: el backend solo acepta pedidos desde `http://localhost:5500` o `http://127.0.0.1:5500` (CORS).

**Tests del backend:**

```bash
cd backend
.venv/Scripts/python -m pytest
```

Cubren los criterios 1 a 20 de [spec.md §8](spec.md), el contrato de la §11, los triggers de la base, la concurrencia (con hilos y con procesos) y CORS.

**Volver a los datos de ejemplo:** con el backend detenido, `cd backend` y `.venv/Scripts/python seed.py --reset`. Borra `turnos.db` y la vuelve a sembrar con fechas relativas a hoy.

### Qué cambia respecto de la Fase 1

- **Los turnos viven en el servidor.** `prototipo-turnos.html` los pide con `GET /api/turnos` y reserva o cancela con `POST`. Si el backend no responde, muestra "Sin conexión con el servidor" y no vuelve a datos en memoria.
- **El selector de usuario es la identidad.** El id elegido viaja en el encabezado `X-Usuario-Id` ([spec.md D-06](spec.md)); el rol lo lee el backend de la base.
- **Los errores vienen del servidor**, con el código de [spec.md §7](spec.md) (por ejemplo `409 SLOT_UNAVAILABLE` o `409 CANCELLATION_WINDOW_EXPIRED`).
- **Hora real.** No hay reloj simulado: el backend usa la hora UTC real.
- **Todo viene del servidor (spec v2.1.0).** Servicios, horarios, disponibilidad, bloqueos, completar / ausente, auditoría y métricas usan los endpoints de [spec.md §11](spec.md). Solo la lista de usuarios sigue local, con los mismos id que la semilla. La verificación de email y los emails no tienen endpoint (spec D-06, D-07).

### Pruebas rápidas de la Fase 2

1. **Persistencia:** reservá un turno como Lucía, recargá la página y después reiniciá el backend. El turno sigue ahí.
2. **Doble reserva real:** en el modal de reserva activá "Otro cliente reserva este slot un instante antes". El servidor rechaza tu reserva con `SLOT_UNAVAILABLE`.
3. **Sin conexión:** detené el backend y recargá. La página avisa y no muestra turnos.
4. **Aislamiento:** con Modo auditoría, pegá en la vista Cliente el id de un turno ajeno (lo ves en el detalle de la vista Administrador). El servidor responde `404`.
5. **Disponibilidad real:** como Sofía, mirá los horarios del lunes de la Dra. Martínez: no aparecen los que ya reservó Lucía.
6. **Bloqueo con conflicto:** en Administrador → Bloqueos, bloqueá un rango con un turno confirmado. El servidor lista el conflicto; con un motivo, cancela el turno y crea el bloqueo en una sola operación. Mirá la pestaña Auditoría.

## Límites conocidos

Fase 1 (`index.html`):

- No hay persistencia: al recargar, los datos vuelven al estado inicial.
- No hay inicio de sesión real; el rol se elige con un selector para poder auditar permisos.
- Los emails son simulados.
- La concurrencia está simulada: las acciones se procesan una detrás de otra. En un sistema real, la garantía contra la doble reserva debe vivir en la base de datos.
- Quedan fuera del prototipo: la reserva en nombre de un cliente, el cambio de horario laboral con turnos ya reservados y el alta de servicios nuevos.

Fase 2 (`prototipo-turnos.html` + `backend/`):

- No hay inicio de sesión: la identidad es el encabezado `X-Usuario-Id` (spec D-06).
- La lista de usuarios del selector es local (no hay endpoint de usuarios); coincide con la semilla.
- No se envían emails (spec D-07).

## Tecnologías

- **Frontend:** HTML, React 18 y Tailwind CSS cargados por CDN, con íconos de Lucide incluidos en el mismo archivo. No hay compilación.
- **Backend (Fase 2):** Python, FastAPI y Uvicorn, con SQLite como base de datos y pytest para los tests.

---

Última actualización: 1 de noviembre de 2026.
