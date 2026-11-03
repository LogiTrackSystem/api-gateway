"""/health: lo usan Render y el pipeline de despliegue para comprobar que la versión nueva quedó viva."""
from fastapi.testclient import TestClient


def _cliente():
    # Se importa aquí (no arriba) para que otros módulos de prueba fijen antes las variables de entorno
    # que app.config lee al importarse.
    from app.main import app

    return TestClient(app)  # sin 'with': no se ejecuta el arranque (calentamiento)


def test_health_devuelve_la_version_de_la_imagen(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    r = _cliente().get("/health")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ok" and cuerpo["service"] == "api-gateway" and cuerpo["version"] == "abc1234"


def test_health_sin_version_configurada_indica_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert _cliente().get("/health").json()["version"] == "dev"
