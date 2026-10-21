import asyncio
import json
import time

import httpx

from .config import CACHE_OPENAPI_S, PREFIJO_API, RUTAS, SERVICIOS

METODOS_HTTP = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

_cache = {"momento": 0.0, "spec": None}


def _ruta_publica(servicio: str, ruta_servicio: str):
    """Traduce una ruta de un microservicio ('/envios/{id}') a la que ve el frontend
    ('/api/v1/envios/{id}'). Devuelve (regla, ruta) o (None, None) si no es pública."""
    for regla in RUTAS:
        if regla.servicio != servicio:
            continue
        if ruta_servicio == regla.destino or ruta_servicio.startswith(regla.destino + "/"):
            resto = ruta_servicio[len(regla.destino):].rstrip("/")
            return regla, f"{PREFIJO_API}/{regla.prefijo}{resto}"
    return None, None


def adaptar_spec(servicio: str, spec: dict) -> tuple[dict, dict]:
    """Toma el openapi.json de un microservicio y devuelve (paths, schemas) listos para unir:
    solo lo público, con las rutas del gateway y los nombres de esquema con prefijo del servicio."""
    etiqueta = servicio.capitalize()
    paths = {}
    for ruta_servicio, item in (spec.get("paths") or {}).items():
        regla, ruta_gateway = _ruta_publica(servicio, ruta_servicio)
        if regla is None:
            continue
        nuevo = {}
        for clave, valor in item.items():
            if clave in METODOS_HTTP:
                if clave.upper() not in regla.metodos:
                    continue
                operacion = dict(valor)
                operacion["tags"] = [f"{servicio} · {t}" for t in (operacion.get("tags") or [regla.prefijo])]
                if operacion.get("operationId"):
                    operacion["operationId"] = f"{servicio}_{operacion['operationId']}"
                nuevo[clave] = operacion
            else:
                nuevo[clave] = valor  # parameters, summary, etc. a nivel de ruta
        if any(m in nuevo for m in METODOS_HTTP):
            paths[ruta_gateway] = nuevo

    schemas = (spec.get("components") or {}).get("schemas") or {}
    paquete = json.dumps({"paths": paths, "schemas": schemas})
    paquete = paquete.replace('"#/components/schemas/', f'"#/components/schemas/{etiqueta}_')
    cargado = json.loads(paquete)
    schemas_nuevos = {f"{etiqueta}_{nombre}": definicion for nombre, definicion in cargado["schemas"].items()}
    return cargado["paths"], schemas_nuevos


async def _descargar(cliente: httpx.AsyncClient, servicio: str, base: str | None):
    if not base:
        return servicio, None
    try:
        resp = await cliente.get(f"{base}/openapi.json", timeout=3.0)
        resp.raise_for_status()
        return servicio, resp.json()
    except Exception:
        return servicio, None


async def construir(cliente: httpx.AsyncClient) -> dict:
    ahora = time.monotonic()
    if _cache["spec"] is not None and ahora - _cache["momento"] < CACHE_OPENAPI_S:
        return _cache["spec"]

    resultados = await asyncio.gather(*[_descargar(cliente, s, u) for s, u in SERVICIOS.items()])

    paths = {
        "/health": {"get": {
            "tags": ["gateway"], "summary": "Salud del gateway",
            "responses": {"200": {"description": "OK"}},
        }},
        f"{PREFIJO_API}/estado": {"get": {
            "tags": ["gateway"], "summary": "Estado de todos los microservicios",
            "description": "Solo administrador.",
            "responses": {"200": {"description": "Estado de cada servicio"}},
        }},
    }
    schemas = {}
    caidos = []
    for servicio, spec in resultados:
        if spec is None:
            caidos.append(servicio)
            continue
        p, s = adaptar_spec(servicio, spec)
        paths.update(p)
        schemas.update(s)

    descripcion = (
        "Punto de entrada único de LogiTrack. Todas las rutas cuelgan de `/api/v1`. "
        "Los errores siguen el formato `{\"detail\": {\"codigo\": ..., \"mensaje\": ...}}`. "
        "Inicie sesión con `POST /api/v1/auth/login` y envíe `Authorization: Bearer <token>` en las demás llamadas "
        "(401 sin sesión o con token vencido, 403 si su rol no tiene permiso)."
    )
    if caidos:
        descripcion += (
            "\n\n**Servicios sin respuesta al generar esta documentación (sus rutas no aparecen):** "
            + ", ".join(sorted(caidos))
        )

    spec_final = {
        "openapi": "3.1.0",
        "info": {"title": "LogiTrack API Gateway", "version": "1.0.0", "description": descripcion},
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
        },
        # Todo requiere Bearer salvo el inicio de sesión y el registro (que se declaran sin seguridad)
        "security": [{"bearerAuth": []}],
    }
    for ruta_publica in ("login", "registro"):
        publica = paths.get(f"{PREFIJO_API}/auth/{ruta_publica}", {}).get("post")
        if publica is not None:
            publica["security"] = []
    _cache["momento"] = ahora
    _cache["spec"] = spec_final
    return spec_final