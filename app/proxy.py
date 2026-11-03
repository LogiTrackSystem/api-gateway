import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .config import RUTAS, SERVICIOS
from .permisos import CABECERAS_IDENTIDAD, ErrorAcceso, autorizar, cabeceras_identidad

# El token NO se reenvía: los servicios reciben la identidad ya verificada en X-User-*.
CABECERAS_REENVIADAS = {"content-type", "accept", "accept-language"}


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
    # Se consume el cuerpo ANTES de decidir: si se responde 401/403/404 sin leerlo, el servidor cierra la
    # conexión con datos pendientes y algunos clientes (p. ej. en Windows) reciben un reinicio de conexión
    # en lugar de la respuesta.
    cuerpo = await request.body()
    regla, resto = resolver(ruta)
    if regla is None:
        return _error(404, "RUTA_NO_ENCONTRADA", f"No existe la ruta /api/v1{ruta}", rid)
    if request.method.upper() not in regla.metodos:
        permitidos = ", ".join(sorted(regla.metodos))
        return _error(405, "METODO_NO_PERMITIDO", f"/api/v1/{regla.prefijo} solo admite: {permitidos}", rid)

    try:
        permiso, ident = autorizar(request.method, ruta, request.headers.get("authorization"))
    except ErrorAcceso as exc:
        return _error(exc.status, exc.codigo, exc.mensaje, rid)
    if permiso is None:  # existe el prefijo y el método pero ninguna regla de permisos: se deniega
        return _error(403, "SIN_PERMISO", f"La ruta /api/v1{ruta} no está habilitada para ningún rol", rid)

    base = SERVICIOS.get(regla.servicio)
    if not base:
        return _error(
            503, "SERVICIO_NO_CONFIGURADO",
            f"Falta la URL del servicio '{regla.servicio}' en el gateway", rid, regla.servicio,
        )

    resto = resto.rstrip("/")
    destino = regla.destino + (resto if resto else "/")  # las colecciones de los servicios terminan en '/'
    cabeceras = {k: v for k, v in request.headers.items() if k.lower() in CABECERAS_REENVIADAS}
    cabeceras["x-request-id"] = rid
    # Se descarta toda identidad enviada desde afuera y se inyecta la verificada del token
    for k in CABECERAS_IDENTIDAD:
        cabeceras.pop(k, None)
    cabeceras.update(cabeceras_identidad(ident))

    params = list(request.query_params.multi_items())
    if ident is not None and ident.rol == "cliente" and permiso.forzar_query_cliente:
        params = [(k, v) for k, v in params if k != "cliente_id"] + [("cliente_id", str(ident.cliente_id))]

    try:
        resp = await cliente.request(
            request.method,
            base + destino,
            params=params,
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