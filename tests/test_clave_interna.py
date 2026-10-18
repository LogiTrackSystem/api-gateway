"""El gateway agrega la clave interna a todas las llamadas que hace a los microservicios."""
from fastapi.testclient import TestClient

from app.interno import cabeceras_internas


def test_sin_clave_no_agrega_cabecera(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    assert cabeceras_internas() == {}


def test_el_cliente_http_del_gateway_envia_la_clave(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-de-prueba-123")
    from app.main import app
    with TestClient(app) as cliente:
        assert cliente.app.state.http.headers["x-internal-key"] == "clave-de-prueba-123"
