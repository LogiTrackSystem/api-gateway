"""Unitaria 2: permisos.autorizar decide por rol quién puede usar cada ruta."""
import pytest

from app.jwt_simple import crear_token
from app.permisos import ErrorAcceso, autorizar

SECRETO = "secreto-de-pruebas-0123456789"


def _bearer(rol):
    return "Bearer " + crear_token({"sub": "u1", "rol": rol, "cliente_id": "c1"}, SECRETO, 3600)


def test_autorizar_exige_token_y_respeta_los_roles(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRETO)
    with pytest.raises(ErrorAcceso) as sin_token:
        autorizar("GET", "/envios", None)
    with pytest.raises(ErrorAcceso) as sin_permiso:
        autorizar("POST", "/envios/abc/cancelar", _bearer("cliente"))
    _, identidad = autorizar("GET", "/envios", _bearer("operador"))
    assert sin_token.value.status == 401 and sin_permiso.value.status == 403
    assert identidad.rol == "operador"
