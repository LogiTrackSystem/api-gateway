import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .config import RUTAS, SERVICIOS

CABECERAS_REENVIADAS = {"content-type", "accept", "accept-language", "authorization"}


def resolver(ruta: str):
    """Dada la ruta que llega después de /api/v1 (por ejemplo '/envios/123'), devuelve la regla
    que la atiende y el resto de la ruta ('/123'). Compara por segmentos completos."""
    for regla in RUTAS:
        base = f"/{regla.prefijo}"
        if ruta == base or ruta.startswith(base + "/"):
            return regla, ruta[len(base):]
    return None, None


def _error(status: int, codigo: str, mensaje: str, rid: str, servicio: str | None = None) -> JSONResponse:
    detalle = {"codigo": codigo, "mensaje": mensaje}
    if servicio:
        detalle["servicio"] = servicio
    return JSONResponse(status_code=status, content={"detail": detalle}, headers={"x-request-id": rid})


async def reenviar(request: Request, ruta: str, cliente: httpx.AsyncClient, rid: str) -> Response:
    inicio = time.perf_counter()
    regla, resto = resolver(ruta)
    if regla is None:
        return _error(404, "RUTA_NO_ENCONTRADA", f"No existe la ruta /api/v1{ruta}", rid)
    if request.method.upper() not in regla.metodos:
        permitidos = ", ".join(sorted(regla.metodos))
        return _error(405, "METODO_NO_PERMITIDO", f"/api/v1/{regla.prefijo} solo admite: {permitidos}", rid)

    base = SERVICIOS.get(regla.servicio)
    if not base:
        return _error(
            503, "SERVICIO_NO_CONFIGURADO",
            f"Falta la URL del servicio '{regla.servicio}' en el gateway", rid, regla.servicio,
        )

    resto = resto.rstrip("/")
    destino = regla.destino + (resto if resto else "/")  # las colecciones de los servicios terminan en '/'
    cuerpo = await request.body()
    cabeceras = {k: v for k, v in request.headers.items() if k.lower() in CABECERAS_REENVIADAS}
    cabeceras["x-request-id"] = rid

    try:
        resp = await cliente.request(
            request.method,
            base + destino,
            params=list(request.query_params.multi_items()),
            content=cuerpo or None,
            headers=cabeceras,
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        respuesta = _error(
            503, "SERVICIO_NO_DISPONIBLE",
            f"El servicio '{regla.servicio}' no está disponible en este momento", rid, regla.servicio,
        )
    except httpx.TimeoutException:
        respuesta = _error(
            504, "SERVICIO_LENTO",
            f"El servicio '{regla.servicio}' tardó demasiado en responder", rid, regla.servicio,
        )
    except httpx.HTTPError as exc:
        respuesta = _error(
            502, "ERROR_DE_GATEWAY",
            f"No se pudo comunicar con '{regla.servicio}' ({type(exc).__name__})", rid, regla.servicio,
        )
    else:
        cabeceras_resp = {"x-request-id": rid, "x-gateway-servicio": regla.servicio}
        tipo = resp.headers.get("content-type")
        if tipo:
            cabeceras_resp["content-type"] = tipo
        respuesta = Response(content=resp.content, status_code=resp.status_code, headers=cabeceras_resp)

    ms = (time.perf_counter() - inicio) * 1000
    print(f"[gateway] {request.method} /api/v1{ruta} -> {regla.servicio} {respuesta.status_code} {ms:.0f}ms rid={rid}")
    return respuesta