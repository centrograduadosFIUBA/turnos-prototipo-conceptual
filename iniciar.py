"""Levanta backend (8000) y frontend (5500) con un solo comando, cada uno en su propio proceso.

Las capas siguen separadas (plan.md §3): esto solo evita abrir dos terminales.
Usa siempre el Python de backend/.venv, aunque se ejecute con otro intérprete.

Uso (desde la raíz del proyecto):
    python iniciar.py            # levanta los dos
    python iniciar.py --abrir    # y además abre la app en el navegador
Ctrl+C detiene ambos. Si uno de los dos se cae, el otro también se detiene.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BACKEND = RAIZ / "backend"
PUERTO_API = 8000   # API_BASE en prototipo-turnos.html
PUERTO_WEB = 5500   # origen permitido por CORS (backend/config.py)
URL_APP = f"http://localhost:{PUERTO_WEB}/prototipo-turnos.html"
URL_DOCS = f"http://localhost:{PUERTO_API}/docs"
WINDOWS = os.name == "nt"


def python_del_venv() -> Path:
    py = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    if not py.exists():
        sys.exit("No encontré backend/.venv. Crealo primero (ver README, «Cómo correr la Fase 2»):\n"
                 "    cd backend\n    python -m venv .venv\n"
                 "    .venv/Scripts/python -m pip install -r requirements.txt")
    return py


def puerto_ocupado(puerto: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def lanzar(cmd: list[str], cwd: Path) -> subprocess.Popen:
    # Grupo/sesión propia: permite detener el proceso junto con sus hijos (uvicorn --reload crea uno).
    extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=cwd, **extra)


def detener(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    try:
        if WINDOWS:
            p.send_signal(signal.CTRL_BREAK_EVENT)          # cierre ordenado de todo el grupo
        else:
            os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        if WINDOWS:                                          # mata el árbol completo, hijos incluidos
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            os.killpg(p.pid, signal.SIGKILL)
        p.wait()


def esperar_listo(url: str, procesos: list[subprocess.Popen], segundos: float = 20) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if any(p.poll() is not None for p in procesos):
            return False
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except OSError:
            time.sleep(0.3)
    return False


def interrumpir(*_) -> None:
    raise KeyboardInterrupt


def main() -> int:
    # Ctrl+Break (Windows) o SIGTERM se tratan igual que Ctrl+C: detener ambos servidores en orden.
    signal.signal(signal.SIGBREAK if WINDOWS else signal.SIGTERM, interrumpir)
    parser = argparse.ArgumentParser(description="Levanta backend (8000) y frontend (5500) juntos.")
    parser.add_argument("--abrir", action="store_true", help="abre la app en el navegador cuando esté lista")
    args = parser.parse_args()

    py = str(python_del_venv())
    ocupados = [p for p in (PUERTO_API, PUERTO_WEB) if puerto_ocupado(p)]
    if ocupados:
        sys.exit(f"Puerto(s) en uso: {', '.join(map(str, ocupados))}. "
                 "Cerrá el servidor que ya está corriendo y volvé a intentar.")

    api = lanzar([py, "-m", "uvicorn", "main:app", "--reload", "--port", str(PUERTO_API)], BACKEND)
    web = lanzar([py, "-m", "http.server", str(PUERTO_WEB), "--bind", "127.0.0.1"], RAIZ)
    procesos = [api, web]

    try:
        # Se sondea 127.0.0.1 y no "localhost": en Windows, localhost prueba ::1 primero y cada intento tarda ~2 s.
        if not (esperar_listo(URL_DOCS.replace("localhost", "127.0.0.1"), procesos)
                and esperar_listo(URL_APP.replace("localhost", "127.0.0.1"), procesos)):
            print("\nNo se pudo levantar alguno de los servidores; revisá los mensajes de arriba.", file=sys.stderr)
            return 1
        print(f"\n  App:  {URL_APP}\n  API:  {URL_DOCS}\n\n  Ctrl+C para detener ambos.\n", flush=True)
        if args.abrir:
            webbrowser.open(URL_APP)
        while all(p.poll() is None for p in procesos):
            time.sleep(0.5)
        print("\nUno de los servidores se detuvo; cierro el otro.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDeteniendo servidores…")
        return 0
    finally:
        for p in procesos:
            detener(p)


if __name__ == "__main__":
    sys.exit(main())
