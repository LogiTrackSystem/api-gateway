"""Integración: petición HTTP al gateway -> control de acceso -> reenvío al microservicio (simulado)."""
import os

os.environ["JWT_SECRET"] = "secreto-de-pruebas-0123456789"
for nombre in ("FLEET", "SHIPMENT", "ROUTING", "TRACKING", "MAINTENANCE", "CUSTOMS", "NOTIFICATION", "BILLING", "ANALYTICS"):
    os.environ[f"{nombre}_SERVICE_URL"] = f"http://{nombre.lower()}.test"

import httpx
from fastapi.testclient import TestClient

from app.jwt_simple import crear_token
from app.main import app


def test_gateway_rechaza_sin_token_y_reenvia_con_identidad_al_servicio():
    recibidas = []

    def servicio_falso(request: httpx.Request) -> httpx.Response:
        recibidas.append(request)
        return httpx.Response(200, json={"ok": True})

    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(servicio_falso))
    gw = TestClient(app)
    token = crear_token({"sub": "u1", "rol": "operador"}, os.environ["JWT_SECRET"], 3600)
    sin_token = gw.get("/api/v1/envios")
    con_token = gw.get("/api/v1/envios", headers={"Authorization": f"Bearer {token}"})
    assert sin_token.status_code == 401 and recibidas[0].headers["x-user-rol"] == "operador"
    assert con_token.status_code == 200 and len(recibidas) == 1
