import os

# La suite nunca debe llamar a un receptor real: una variable ya definida (aunque vacía) no la pisa `.env`.
# Se fija al importar para que también la herede el uvicorn de las pruebas de integración.
os.environ["WEBHOOK_NOTIFY_URL"] = ""
