"""Base de conocimiento vectorial (spec §15, INV-06) — ChromaDB local con similitud coseno.

Funciones reutilizables (las importa `main.py` y `agent.py`):
    dividir_en_chunks(texto)                      -> list[str]   chunks semánticos (por sección/párrafo)
    ingestar_texto(texto, nombre_archivo)         -> int         indexa (reemplaza lo anterior del mismo archivo)
    ingestar_archivo(ruta)                        -> int
    buscar_conocimiento(pregunta, top_k=3)        -> list[dict]  Top-K por similitud coseno

Por consola:  python ingestar_conocimiento.py [archivo ...]   (sin argumentos indexa politicas_consultorio.md)

El almacén es independiente de turnos.db: no agrega tablas al esquema SQLite (spec §12).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import chromadb

RAIZ = Path(__file__).resolve().parent
ARCHIVO_POR_DEFECTO = RAIZ / "politicas_consultorio.md"
COLECCION = "conocimiento"
MAX_CHARS_CHUNK = 900  # una sección más larga se subdivide por párrafos

# Se leen en cada llamada para poder cambiarlas en los tests (monkeypatch) o por entorno.
CHROMA_PATH: Path = Path(os.environ.get("CHROMA_PATH", RAIZ / "chroma_db"))
EMBEDDING_FUNCTION = None  # None = el modelo local por defecto de Chroma (all-MiniLM-L6-v2, ONNX)

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


# ----------------------------------------------------------------------------
# Chunking
# ----------------------------------------------------------------------------
def _subdividir(texto: str, limite: int) -> list[str]:
    """Parte un bloque largo por párrafos (línea en blanco) sin cortar párrafos a la mitad."""
    partes, actual = [], ""
    for parrafo in re.split(r"\n\s*\n", texto):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        if actual and len(actual) + len(parrafo) + 2 > limite:
            partes.append(actual)
            actual = ""
        actual = f"{actual}\n\n{parrafo}" if actual else parrafo
    if actual:
        partes.append(actual)
    return partes


def dividir_en_chunks(texto: str, max_chars: int = MAX_CHARS_CHUNK) -> list[str]:
    """Divide Markdown o texto plano en chunks semánticos.

    Cada chunk es una sección (encabezado + contenido) y lleva la ruta de encabezados como prefijo
    ("Especialidades > Cardiología"), para que el fragmento sea autoexplicativo al recuperarlo.
    Las secciones largas se subdividen por párrafos; el texto plano se divide solo por párrafos.
    """
    secciones: list[tuple[list[str], list[str]]] = []  # (ruta de títulos, líneas de contenido)
    ruta: list[tuple[int, str]] = []
    contenido: list[str] = []

    def cerrar() -> None:
        if any(l.strip() for l in contenido):
            secciones.append(([t for _, t in ruta], contenido.copy()))
        contenido.clear()

    for linea in texto.replace("\r\n", "\n").split("\n"):
        m = _HEADING.match(linea)
        if m:
            cerrar()
            nivel = len(m.group(1))
            while ruta and ruta[-1][0] >= nivel:
                ruta.pop()
            ruta.append((nivel, m.group(2).strip()))
        elif linea.strip() == "---":  # separador horizontal de Markdown: no es contenido
            continue
        else:
            contenido.append(linea)
    cerrar()

    chunks: list[str] = []
    for titulos, lineas in secciones:
        cuerpo = "\n".join(lineas).strip()
        # El título del documento (H1) se omite del prefijo cuando hay subtítulos: aporta ruido al embedding.
        prefijo = " > ".join(titulos[1:] if len(titulos) > 1 else titulos)
        for parte in ([cuerpo] if len(cuerpo) <= max_chars else _subdividir(cuerpo, max_chars)):
            chunks.append(f"{prefijo}\n{parte}" if prefijo else parte)
    return chunks


# ----------------------------------------------------------------------------
# Almacén vectorial
# ----------------------------------------------------------------------------
def _coleccion():
    """Colección persistente con distancia coseno (se crea si no existe)."""
    cliente = chromadb.PersistentClient(path=str(CHROMA_PATH))
    kwargs = {"embedding_function": EMBEDDING_FUNCTION} if EMBEDDING_FUNCTION is not None else {}
    return cliente.get_or_create_collection(COLECCION, metadata={"hnsw:space": "cosine"}, **kwargs)


def ingestar_texto(texto: str, nombre_archivo: str) -> int:
    """Indexa `texto` bajo `nombre_archivo`. Reemplaza los chunks previos del mismo archivo (re-ingesta idempotente).

    Devuelve la cantidad de chunks indexados. Disponible para búsqueda de inmediato, sin reiniciar nada.
    """
    nombre = Path(nombre_archivo).name
    chunks = dividir_en_chunks(texto)
    col = _coleccion()
    col.delete(where={"archivo": nombre})
    if chunks:
        col.add(
            ids=[f"{nombre}::{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"archivo": nombre, "chunk": i} for i in range(len(chunks))],
        )
    return len(chunks)


def ingestar_archivo(ruta: str | Path) -> int:
    ruta = Path(ruta)
    return ingestar_texto(ruta.read_text(encoding="utf-8"), ruta.name)


def buscar_conocimiento(pregunta: str, top_k: int = 3) -> list[dict]:
    """Búsqueda vectorial Top-K por similitud coseno (INV-06).

    Devuelve `[{"texto", "archivo", "distancia", "similitud"}, ...]` ordenado de más a menos relevante;
    `similitud = 1 - distancia_coseno`. Lista vacía si la base no tiene documentos.
    """
    col = _coleccion()
    total = col.count()
    if total == 0 or not pregunta.strip():
        return []
    r = col.query(query_texts=[pregunta], n_results=max(1, min(top_k, total)), include=["documents", "metadatas", "distances"])
    return [
        {"texto": doc, "archivo": meta.get("archivo"), "distancia": round(dist, 4), "similitud": round(1 - dist, 4)}
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])
    ]


if __name__ == "__main__":
    for arg in (sys.argv[1:] or [str(ARCHIVO_POR_DEFECTO)]):
        print(f"{Path(arg).name}: {ingestar_archivo(arg)} chunks indexados en {CHROMA_PATH}")
