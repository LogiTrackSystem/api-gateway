"""JWT HS256 mínimo con la librería estándar (sin dependencias nuevas).

El mismo archivo vive en Shipment (que firma los tokens al iniciar sesión) y en el API Gateway
(que los verifica). Solo admite HS256; rechaza cualquier otro algoritmo (incluido 'none').
"""
import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def _b64e(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def _b64d(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firmar(mensaje: bytes, secreto: str) -> bytes:
    return hmac.new(secreto.encode("utf-8"), mensaje, hashlib.sha256).digest()


def crear_token(claims: dict, secreto: str, vigencia_s: int) -> str:
    ahora = int(time.time())
    cuerpo = {**claims, "iat": ahora, "exp": ahora + int(vigencia_s)}
    cabecera = {"alg": "HS256", "typ": "JWT"}
    partes = [
        _b64e(json.dumps(cabecera, separators=(",", ":")).encode()),
        _b64e(json.dumps(cuerpo, separators=(",", ":"), default=str).encode()),
    ]
    firma = _firmar(".".join(partes).encode("ascii"), secreto)
    return ".".join(partes) + "." + _b64e(firma)


def verificar_token(token: str, secreto: str) -> dict:
    try:
        cabecera_b64, cuerpo_b64, firma_b64 = token.split(".")
        cabecera = json.loads(_b64d(cabecera_b64))
        firma = _b64d(firma_b64)
    except Exception:
        raise TokenError("TOKEN_INVALIDO", "El token no tiene un formato válido")
    if cabecera.get("alg") != "HS256":
        raise TokenError("TOKEN_INVALIDO", "Algoritmo de token no permitido")
    esperada = _firmar(f"{cabecera_b64}.{cuerpo_b64}".encode("ascii"), secreto)
    if not hmac.compare_digest(firma, esperada):
        raise TokenError("TOKEN_INVALIDO", "La firma del token no es válida")
    try:
        cuerpo = json.loads(_b64d(cuerpo_b64))
    except Exception:
        raise TokenError("TOKEN_INVALIDO", "El contenido del token no es válido")
    if int(cuerpo.get("exp", 0)) < int(time.time()):
        raise TokenError("TOKEN_EXPIRADO", "La sesión expiró; inicie sesión de nuevo")
    return cuerpo
