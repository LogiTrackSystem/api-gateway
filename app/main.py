import os
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

FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")
SHIPMENT_SERVICE_URL = os.getenv("SHIPMENT_SERVICE_URL")
ROUTING_SERVICE_URL = os.getenv("ROUTING_SERVICE_URL")
TRACKING_SERVICE_URL = os.getenv("TRACKING_SERVICE_URL")
MAINTENANCE_SERVICE_URL = os.getenv("MAINTENANCE_SERVICE_URL")
CUSTOMS_SERVICE_URL = os.getenv("CUSTOMS_SERVICE_URL")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL")
ANALYTICS_SERVICE_URL = os.getenv("ANALYTICS_SERVICE_URL")


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}


async def _proxy(method: str, url: str, json_body=None, params=None):
    """Delega una request al microservicio de origen."""

    async with httpx.AsyncClient() as client:
        resp = await client.request(method, url, json=json_body, params=params)
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(status_code=resp.status_code, content=content)


# ---------- Vehiculos (Fleet Service) ----------

@app.get("/api/v1/vehiculos")
async def get_vehicles():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/vehiculos/")
        return resp.json()


@app.get("/api/v1/vehiculos/{vehicle_id}")
async def get_vehicle(vehicle_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/vehiculos/{vehicle_id}")
        print(f"DEBUG -> URL llamada: {FLEET_SERVICE_URL}/vehiculos/{vehicle_id}")
        print(f"DEBUG -> status de Fleet: {resp.status_code}, body: {resp.text}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        return resp.json()


@app.post("/api/v1/vehiculos", status_code=201)
async def create_vehicle(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{FLEET_SERVICE_URL}/vehiculos/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.patch("/api/v1/vehiculos/{vehicle_id}/estado")
async def update_vehicle_state(vehicle_id: str, payload: dict):
    return await _proxy("PATCH", f"{FLEET_SERVICE_URL}/vehiculos/{vehicle_id}/estado", json_body=payload)


# ---------- Conductores (Fleet Service) ----------

@app.get("/api/v1/conductores")
async def get_drivers():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/conductores/")
        return resp.json()


@app.post("/api/v1/conductores", status_code=201)
async def create_driver(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{FLEET_SERVICE_URL}/conductores/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


# ---------- Envios (Shipment Service) ----------

@app.post("/api/v1/envios", status_code=201)
async def create_shipment(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{SHIPMENT_SERVICE_URL}/envios/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/api/v1/envios")
async def list_shipments(estado: str | None = None, cliente_id: str | None = None):
    params = {k: v for k, v in {"estado": estado, "cliente_id": cliente_id}.items() if v is not None}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SHIPMENT_SERVICE_URL}/envios/", params=params)
        return resp.json()

@app.get("/health", include_in_schema=False)
def health(request: Request):
    # "calentamiento" dice cuántos microservicios ya despertaron (útil para saber cuándo el sistema está listo)
    activo = getattr(request.app.state, "warmup", None) is not None
    estado = getattr(request.app.state, "warmup_estado", None)
    return {"status": "ok", "service": "api-gateway", "version": os.getenv("APP_VERSION", "dev"), "calentamiento": calentamiento.resumen(estado, activo)}


@app.get("/openapi.json", include_in_schema=False)
async def openapi_json(request: Request):
    return JSONResponse(await openapi_unificado.construir(request.app.state.http))


@app.get("/docs", include_in_schema=False)
async def docs():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="LogiTrack API Gateway")

@app.patch("/api/v1/envios/{envio_id}/asignar")
async def assign_shipment(envio_id: str, payload: dict):
    # _proxy propaga el status real (200/404/422/...) del shipment-service.
    return await _proxy("PATCH", f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/asignar", json_body=payload)

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

@app.patch("/api/v1/envios/{envio_id}/estado")
async def update_shipment_status(envio_id: str, payload: dict):
    # _proxy propaga el status real (200/404/422/...) del shipment-service.
    return await _proxy("PATCH", f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/estado", json_body=payload)

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
@app.post("/api/v1/envios/{envio_id}/prueba-entrega", status_code=201)
async def register_delivery_proof(envio_id: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/prueba-entrega", json=payload)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        return JSONResponse(status_code=resp.status_code, content=resp.json())


# ---------- Routing Service ----------

@app.get("/api/v1/rutas")
async def listar_rutas(envio_id: str | None = None):
    async with httpx.AsyncClient() as client:
        params = {"envio_id": envio_id} if envio_id else {}
        resp = await client.get(f"{ROUTING_SERVICE_URL}/rutas/", params=params)
    return resp.json()


@app.post("/api/v1/rutas", status_code=201)
async def crear_ruta(payload: dict):
    return await _proxy("POST", f"{ROUTING_SERVICE_URL}/rutas/", json_body=payload)


@app.get("/api/v1/rutas/{ruta_id}")
async def obtener_ruta(ruta_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ROUTING_SERVICE_URL}/rutas/{ruta_id}")
    return resp.json()


@app.get("/api/v1/rutas/{ruta_id}/historial")
async def obtener_historial_ruta(ruta_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ROUTING_SERVICE_URL}/rutas/{ruta_id}/historial")
    return resp.json()


@app.patch("/api/v1/rutas/{ruta_id}/recalcular")
async def recalcular_ruta(ruta_id: str, payload: dict):
    return await _proxy("PATCH", f"{ROUTING_SERVICE_URL}/rutas/{ruta_id}/recalcular", json_body=payload)


# ---------- Tracking Ingestion Service ----------

@app.post("/api/v1/telemetria", status_code=201)
async def crear_lectura_telemetria(payload: dict):
    return await _proxy("POST", f"{TRACKING_SERVICE_URL}/telemetria/", json_body=payload)


@app.get("/api/v1/telemetria/{vehiculo_id}")
async def obtener_telemetria(vehiculo_id: str, limite: int = 100):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{TRACKING_SERVICE_URL}/telemetria/{vehiculo_id}", params={"limite": limite})
    return resp.json()


# ---------- Maintenance Service ----------

@app.post("/api/v1/programas", status_code=201)
async def crear_programa_mantenimiento(payload: dict):
    return await _proxy("POST", f"{MAINTENANCE_SERVICE_URL}/programas/", json_body=payload)


@app.get("/api/v1/programas/{vehiculo_id}")
async def obtener_programas_mantenimiento(vehiculo_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{MAINTENANCE_SERVICE_URL}/programas/{vehiculo_id}")
    return resp.json()


@app.post("/api/v1/intervenciones", status_code=201)
async def crear_intervencion_mantenimiento(payload: dict):
    return await _proxy("POST", f"{MAINTENANCE_SERVICE_URL}/intervenciones/", json_body=payload)


@app.get("/api/v1/intervenciones/{vehiculo_id}")
async def obtener_intervenciones(vehiculo_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{MAINTENANCE_SERVICE_URL}/intervenciones/{vehiculo_id}")
    return resp.json()


# ---------- Customs Service ----------

@app.get("/api/v1/declaraciones")
async def listar_declaraciones(estado: str | None = None):
    async with httpx.AsyncClient() as client:
        params = {"estado": estado} if estado else {}
        resp = await client.get(f"{CUSTOMS_SERVICE_URL}/declaraciones/", params=params)
    return resp.json()


@app.get("/api/v1/declaraciones/{envio_id}")
async def obtener_declaracion(envio_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CUSTOMS_SERVICE_URL}/declaraciones/{envio_id}")
    return resp.json()


@app.patch("/api/v1/declaraciones/{declaracion_id}/estado")
async def actualizar_estado_declaracion(declaracion_id: str, payload: dict):
    return await _proxy("PATCH", f"{CUSTOMS_SERVICE_URL}/declaraciones/{declaracion_id}/estado", json_body=payload)


# ---------- Notification Service ----------

@app.get("/api/v1/notificaciones")
async def listar_notificaciones(limite: int = 50):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{NOTIFICATION_SERVICE_URL}/notificaciones/", params={"limite": limite})
    return resp.json()


@app.get("/api/v1/preferencias/{cliente_id}")
async def obtener_preferencia(cliente_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{NOTIFICATION_SERVICE_URL}/preferencias/{cliente_id}")
    return resp.json()


@app.post("/api/v1/preferencias/{cliente_id}")
async def configurar_preferencia(cliente_id: str, payload: dict):
    return await _proxy("POST", f"{NOTIFICATION_SERVICE_URL}/preferencias/{cliente_id}", json_body=payload)


# ---------- Billing Service ----------

@app.get("/api/v1/facturas")
async def listar_facturas(cliente_id: str | None = None, periodo: str | None = None, estado: str | None = None):
    params = {k: v for k, v in {"cliente_id": cliente_id, "periodo": periodo, "estado": estado}.items() if v}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BILLING_SERVICE_URL}/facturas/", params=params)
    return resp.json()


@app.get("/api/v1/facturas/{factura_id}")
async def obtener_factura(factura_id: str):
    return await _proxy("GET", f"{BILLING_SERVICE_URL}/facturas/{factura_id}")


@app.post("/api/v1/facturas/cerrar-periodo")
async def cerrar_periodo_facturacion():
    return await _proxy("POST", f"{BILLING_SERVICE_URL}/facturas/cerrar-periodo")


@app.get("/api/v1/costos-ruta")
async def listar_costos_ruta(envio_id: str | None = None):
    params = {"envio_id": envio_id} if envio_id else {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BILLING_SERVICE_URL}/costos-ruta/", params=params)
    return resp.json()


@app.post("/api/v1/tarifas", status_code=201)
async def configurar_tarifa(payload: dict):
    return await _proxy("POST", f"{BILLING_SERVICE_URL}/tarifas/", json_body=payload)


@app.get("/api/v1/tarifas/{cliente_id}")
async def obtener_tarifa(cliente_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BILLING_SERVICE_URL}/tarifas/{cliente_id}")
    return resp.json()


# ---------- Analytics Service ----------

@app.get("/api/v1/analytics/resumen")
async def analytics_resumen():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/resumen")
    return resp.json()


@app.get("/api/v1/analytics/entregas-diarias")
async def analytics_entregas_diarias(dias: int = 30):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/entregas-diarias", params={"dias": dias})
    return resp.json()


@app.get("/api/v1/analytics/utilizacion-flota")
async def analytics_utilizacion_flota():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/utilizacion-flota")
    return resp.json()


@app.get("/api/v1/analytics/costo-por-km")
async def analytics_costo_por_km():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/costo-por-km")
    return resp.json()


@app.get("/api/v1/analytics/eficiencia-combustible")
async def analytics_eficiencia_combustible(limite: int = 50):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/eficiencia-combustible", params={"limite": limite})
    return resp.json()


@app.get("/api/v1/analytics/proyeccion-mantenimiento")
async def analytics_proyeccion_mantenimiento(dias: int = 90):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/proyeccion-mantenimiento", params={"dias": dias})
    return resp.json()


@app.get("/api/v1/analytics/actividad-reciente")
async def analytics_actividad_reciente(limite: int = 20):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/actividad-reciente", params={"limite": limite})
    return resp.json()


@app.post("/api/v1/analytics/etl")
async def analytics_etl_ejecutar():
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{ANALYTICS_SERVICE_URL}/etl/ejecutar")
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(status_code=resp.status_code, content=content)
