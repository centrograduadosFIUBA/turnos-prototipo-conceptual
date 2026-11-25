import os
from pathlib import Path

# La suite nunca debe llamar a un receptor real: se ignora el `.env` del proyecto (apuntando a un archivo que
# no existe) y la variable queda vacía. Se fija al importar para que lo herede el uvicorn de integración.
os.environ["WEBHOOK_ENV_FILE"] = str(Path(__file__).with_name("sin-archivo.env"))
os.environ["WEBHOOK_NOTIFY_URL"] = ""
