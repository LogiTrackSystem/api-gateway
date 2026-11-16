"""Unitaria 1: jwt_simple.verificar_token valida firma y vigencia del token."""
import pytest

from app.jwt_simple import TokenError, crear_token, verificar_token

SECRETO = "secreto-de-pruebas-0123456789"


def test_verificar_token_acepta_el_valido_y_rechaza_firma_falsa_y_expirado():
    assert verificar_token(crear_token({"sub": "u1", "rol": "cliente"}, SECRETO, 3600), SECRETO)["sub"] == "u1"
    with pytest.raises(TokenError) as firma:
        verificar_token(crear_token({"sub": "u1"}, "otro-secreto-0123456789", 3600), SECRETO)
    with pytest.raises(TokenError) as expirado:
        verificar_token(crear_token({"sub": "u1"}, SECRETO, -10), SECRETO)
    assert firma.value.codigo == "TOKEN_INVALIDO" and expirado.value.codigo == "TOKEN_EXPIRADO"
