import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from .interno import cabeceras_internas
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse

from . import calentamiento, openapi_unificado
from .config import SERVICIOS, TIMEOUT_LECTURA_S, origenes_cors
from .permisos import ErrorAcceso, autorizar
from .proxy import reenviar


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        headers=cabeceras_internas(),
        timeout=httpx.Timeout(TIMEOUT_LECTURA_S, connect=3.0, write=10.0, pool=5.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    # Despierta los microservicios en segundo plano: el gateway ya atiende peticiones mientras tanto.
    app.state.warmup_estado = {}
    app.state.warmup = calentamiento.iniciar(estado=app.state.warmup_estado)
    yield
    await calentamiento.detener(app.state.warmup)
    await app.state.http.aclose()


# La documentación se genera uniendo la de los microservicios (ver openapi_unificado.py)
app = FastAPI(title="LogiTrack API Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

_origenes = origenes_cors()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in _origenes else _origenes,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Gateway-Servicio"],
)


@app.get("/health", include_in_schema=False)
def health(request: Request):
    # "calentamiento" dice cuántos microservicios ya despertaron (útil para saber cuándo el sistema está listo)
    activo = getattr(request.app.state, "warmup", None) is not None
    estado = getattr(request.app.state, "warmup_estado", None)
    return {"status": "ok", "service": "api-gateway", "calentamiento": calentamiento.resumen(estado, activo)}


@app.get("/openapi.json", include_in_schema=False)
async def openapi_json(request: Request):
    return JSONResponse(await openapi_unificado.construir(request.app.state.http))


@app.get("/docs", include_in_schema=False)
async def docs():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="LogiTrack API Gateway")


async def _salud(cliente: httpx.AsyncClient, servicio: str, base: str | None):
    if not base:
        return servicio, {"estado": "sin_configurar"}
    inicio = time.perf_counter()
    try:
        resp = await cliente.get(f"{base}/health", timeout=3.0)
        ms = round((time.perf_counter() - inicio) * 1000)
        return servicio, {"estado": "ok" if resp.status_code == 200 else "con_error", "ms": ms}
    except Exception:
        return servicio, {"estado": "sin_respuesta"}


@app.get("/api/v1/estado")
async def estado_de_servicios(request: Request):
    """Consulta la salud de cada microservicio (útil para el panel del frontend y para las demos). Solo administrador."""
    try:
        autorizar("GET", "/estado", request.headers.get("authorization"))
    except ErrorAcceso as exc:
        return JSONResponse(status_code=exc.status, content={"detail": {"codigo": exc.codigo, "mensaje": exc.mensaje}})
    resultados = await asyncio.gather(*[_salud(request.app.state.http, s, u) for s, u in SERVICIOS.items()])
    servicios = dict(resultados)
    ok = all(v["estado"] == "ok" for v in servicios.values())
    return {"estado_general": "ok" if ok else "degradado", "servicios": servicios}


@app.api_route("/api/v1/{ruta:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def proxy(ruta: str, request: Request):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    return await reenviar(request, "/" + ruta, request.app.state.http, rid)