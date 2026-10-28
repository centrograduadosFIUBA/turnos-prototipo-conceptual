"""Carga turnos de ejemplo en turnos.db, equivalentes al mock de index.html (15 turnos).

Las fechas son relativas a "ahora" (UTC). Inserta directo en la base porque la API no puede crear
turnos pasados ni en estado COMPLETADO/AUSENTE.

Uso:  python seed_demo.py            (falla si ya hay turnos)
      python seed_demo.py --reset    (borra todos los turnos y recarga)
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone

import main

main.init_db()
now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
today = now.replace(hour=0, minute=0)


def day(offset: int, hour: int, minute: int = 0) -> datetime:
    return today + timedelta(days=offset, hours=hour, minutes=minute)


def ahead(minutes: int) -> datetime:  # "ahora + X", redondeado hacia arriba a la grilla de 15 min
    t = now + timedelta(minutes=minutes)
    return t + timedelta(minutes=(-t.minute) % 15)


DURATION = {sid: m for (sid, _p, _n, _d, m, _pr) in main.SEED_SERVICES}
PROF = {sid: p for (sid, p, *_rest) in main.SEED_SERVICES}

# (n, cliente, servicio, inicio, estado, cancelado_por, motivo)
TURNOS = [
    (1, "c1", "s1", day(-3, 9), "COMPLETADO", None, None),
    (2, "c3", "s2", day(-3, 10), "COMPLETADO", None, None),
    (3, "c1", "s3", day(-2, 10), "COMPLETADO", None, None),
    (4, "c3", "s5", day(-2, 11), "AUSENTE", None, None),
    (5, "c2", "s1", day(-1, 9, 30), "COMPLETADO", None, None),
    (6, "c1", "s4", day(-1, 15), "CANCELADO", "c1", None),
    (7, "c3", "s6", day(-1, 10), "CANCELADO", "p3", "Imprevisto médico"),
    (8, "c1", "s1", ahead(90), "CONFIRMADO", None, None),    # dentro de las 2 h: cancelar da 409 (INV-01)
    (9, "c3", "s5", ahead(180), "CONFIRMADO", None, None),   # en ~3 h: cancelable
    (10, "c2", "s3", ahead(270), "CONFIRMADO", None, None),
    (11, "c1", "s2", ahead(360), "CONFIRMADO", None, None),
    (12, "c3", "s1", day(1, 10), "CONFIRMADO", None, None),
    (13, "c1", "s4", day(1, 11), "CONFIRMADO", None, None),
    (14, "c2", "s5", day(2, 9), "CONFIRMADO", None, None),
    (15, "c1", "s2", day(3, 15, 30), "CONFIRMADO", None, None),
]

with main.write_tx() as conn:
    existing = conn.execute("SELECT COUNT(*) FROM turno").fetchone()[0]
    if existing and "--reset" not in sys.argv:
        sys.exit(f"Ya hay {existing} turnos. Usá --reset para reemplazarlos.")
    conn.execute("DELETE FROM turno")
    created = main.fmt(now - timedelta(days=5))
    for n, cliente, svc, inicio, estado, by, motivo in TURNOS:
        conn.execute(
            "INSERT INTO turno (id, cliente_id, profesional_id, servicio_id, inicio, fin, estado,"
            " motivo_cancelacion, cancelado_por_id, creado_en, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid5(uuid.NAMESPACE_DNS, f"turno-demo-{n}")), cliente, PROF[svc], svc, main.fmt(inicio),
             main.fmt(inicio + timedelta(minutes=DURATION[svc])), estado, motivo, by, created, created),
        )
        print(f"t{n:<2} {estado:<10} {cliente} {svc} {main.fmt(inicio)}")
print(f"\n{len(TURNOS)} turnos cargados en {main.DB_PATH}")
