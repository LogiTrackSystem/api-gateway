"""Pruebas del control de acceso del gateway. Los microservicios se simulan con httpx.MockTransport."""
import os
import sys

os.environ["JWT_SECRET"] = "secreto-de-pruebas-0123456789"
for nombre in ("FLEET", "SHIPMENT", "ROUTING", "TRACKING", "MAINTENANCE", "CUSTOMS", "NOTIFICATION", "BILLING", "ANALYTICS"):
    os.environ[f"{nombre}_SERVICE_URL"] = f"http://{nombre.lower()}.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest
from fastapi.testclient import TestClient

from app.jwt_simple import crear_token
from app.main import app

SECRETO = os.environ["JWT_SECRET"]
CLIENTE_A = "11111111-1111-1111-1111-111111111111"
CLIENTE_B = "22222222-2222-2222-2222-222222222222"
recibidas = []


def _servicio_falso(request: httpx.Request) -> httpx.Response:
    recibidas.append(request)
    return httpx.Response(200, json={"ok": True})


@pytest.fixture()
def gw():
    recibidas.clear()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(_servicio_falso))
    yield TestClient(app)


def token(rol, cliente_id=None, vigencia=3600, secreto=SECRETO):
    return crear_token({"sub": "99999999-9999-9999-9999-999999999999", "rol": rol, "cliente_id": cliente_id, "nombre": "T"},
                       secreto, vigencia)


def auth(rol, cliente_id=None):
    if rol == "cliente" and cliente_id is None:
        cliente_id = CLIENTE_A
    return {"Authorization": f"Bearer {token(rol, cliente_id)}"}


# ---------- autenticación ----------

def test_sin_token_es_401(gw):
    r = gw.get("/api/v1/envios")
    assert r.status_code == 401 and r.json()["detail"]["codigo"] == "NO_AUTENTICADO"
    assert recibidas == []


def test_token_manipulado_o_con_otra_clave_es_401(gw):
    r = gw.get("/api/v1/envios", headers={"Authorization": f"Bearer {token('administrador', secreto='otra-clave-distinta-123456')}"})
    assert r.status_code == 401 and r.json()["detail"]["codigo"] == "TOKEN_INVALIDO"
    assert gw.get("/api/v1/envios", headers={"Authorization": "Bearer basura"}).status_code == 401


def test_token_expirado_es_401(gw):
    r = gw.get("/api/v1/envios", headers={"Authorization": f"Bearer {token('administrador', vigencia=-10)}"})
    assert r.status_code == 401 and r.json()["detail"]["codigo"] == "TOKEN_EXPIRADO"


def test_login_es_publico_y_llega_a_shipment(gw):
    r = gw.post("/api/v1/auth/login", json={"email": "a@x.co", "password": "12345678"})
    assert r.status_code == 200
    assert str(recibidas[0].url) == "http://shipment.test/auth/login"


def test_registro_es_publico_y_llega_a_shipment_sin_identidad_falsa(gw):
    cuerpo = {"nombre": "Ana", "email": "a@x.co", "password": "12345678", "tipo_documento": "CC", "numero_documento": "123"}
    r = gw.post("/api/v1/auth/registro", json=cuerpo, headers={"X-User-Rol": "administrador", "X-User-Id": "falso"})
    assert r.status_code == 200
    assert str(recibidas[0].url) == "http://shipment.test/auth/registro"
    assert "x-user-rol" not in recibidas[0].headers and "x-user-id" not in recibidas[0].headers


def test_registro_solo_acepta_post(gw):
    assert gw.get("/api/v1/auth/registro").status_code in (401, 403, 405)
    assert recibidas == []


def test_ruta_inexistente_sigue_siendo_404_y_metodo_no_permitido_405(gw):
    assert gw.get("/api/v1/nada").status_code == 404
    assert gw.delete("/api/v1/envios/1", headers=auth("administrador")).status_code == 405


# ---------- identidad hacia los servicios ----------

def test_gateway_ignora_cabeceras_de_identidad_falsas_y_no_reenvia_el_token(gw):
    h = {**auth("cliente"), "X-User-Rol": "administrador", "X-Cliente-Id": CLIENTE_B, "X-User-Id": "falso"}
    assert gw.get("/api/v1/envios", headers=h).status_code == 200
    llegada = recibidas[0].headers
    assert llegada["x-user-rol"] == "cliente"
    assert llegada["x-cliente-id"] == CLIENTE_A
    assert llegada["x-user-id"] == "99999999-9999-9999-9999-999999999999"
    assert "authorization" not in llegada


def test_cabeceras_falsas_en_login_publico_tampoco_pasan(gw):
    gw.post("/api/v1/auth/login", json={"email": "a@x.co", "password": "12345678"}, headers={"X-User-Rol": "administrador"})
    assert "x-user-rol" not in recibidas[0].headers


# ---------- matriz de permisos ----------

PERMITIDO = [
    ("cliente", "POST", "/envios"), ("cliente", "GET", "/envios/abc/eventos"), ("cliente", "POST", "/viabilidad"),
    ("cliente", "POST", "/envios/cotizar"), ("cliente", "GET", "/clientes"), ("cliente", "GET", "/ubicaciones"),
    ("cliente", "GET", "/facturas"), ("cliente", "GET", "/cotizaciones"), ("cliente", "GET", "/pagos"),
    ("cliente", "GET", "/pagos/envio/abc"), ("cliente", "GET", "/facturas-pedido"), ("cliente", "GET", "/facturas-pedido/abc"),
    ("operador", "GET", "/pagos"), ("operador", "GET", "/cotizaciones"), ("administrador", "GET", "/facturas-pedido"),
    ("operador", "POST", "/clientes"), ("operador", "PATCH", "/clientes/abc"), ("operador", "POST", "/rutas-maestras/calcular"),
    ("operador", "GET", "/envios/programados"), ("operador", "POST", "/envios/abc/prueba-entrega"),
    ("operador", "PATCH", "/envios/abc/estado"), ("operador", "GET", "/seguimiento/x"), ("operador", "GET", "/declaraciones"),
    ("operador", "PATCH", "/declaraciones/x"), ("operador", "GET", "/notificaciones"), ("operador", "GET", "/vehiculos"),
    ("gestor_flota", "POST", "/vehiculos"), ("gestor_flota", "PATCH", "/vehiculos/x/estado"), ("gestor_flota", "POST", "/conductores"),
    ("gestor_flota", "POST", "/intervenciones"), ("gestor_flota", "POST", "/envios/abc/cancelar"),
    ("gestor_flota", "PATCH", "/envios/abc/reprogramar"), ("gestor_flota", "GET", "/dashboard/utilizacion-flota"),
    ("gestor_flota", "GET", "/dashboard/proyeccion-mantenimiento"), ("gestor_flota", "GET", "/envios/programados"),
    ("gestor_flota", "POST", "/envios/abc/reintentar-asignacion"),
    ("administrador", "GET", "/usuarios"), ("administrador", "POST", "/usuarios"), ("administrador", "GET", "/dashboard/resumen"),
    ("administrador", "GET", "/dashboard/ingresos/mensual"), ("administrador", "GET", "/dashboard/ingresos/anual"),
    ("administrador", "GET", "/dashboard/ingresos/pedidos"),
    ("administrador", "POST", "/pagos/abc/reembolsar"), ("administrador", "GET", "/pagos/por-reembolsar"),
    ("administrador", "POST", "/etl/ejecutar"), ("administrador", "POST", "/facturas/cerrar-periodo"), ("administrador", "GET", "/tarifas/x"),
    ("administrador", "POST", "/tarifas"), ("administrador", "GET", "/costos-ruta"), ("administrador", "GET", "/estado"),
]

DENEGADO = [
    ("cliente", "GET", "/usuarios"), ("cliente", "POST", "/clientes"), ("cliente", "PATCH", "/clientes/abc"),
    ("cliente", "POST", "/ubicaciones"), ("cliente", "GET", "/rutas-maestras"), ("cliente", "GET", "/vehiculos"),
    ("cliente", "GET", "/conductores"), ("cliente", "GET", "/seguimiento/x"), ("cliente", "GET", "/telemetria/x"),
    ("cliente", "GET", "/simulaciones/x"), ("cliente", "GET", "/envios/programados"), ("cliente", "POST", "/envios/abc/cancelar"),
    ("cliente", "PATCH", "/envios/abc/reprogramar"), ("cliente", "PATCH", "/envios/abc/estado"),
    ("cliente", "POST", "/envios/abc/reintentar-asignacion"), ("cliente", "GET", "/declaraciones"),
    ("cliente", "GET", "/notificaciones"), ("cliente", "GET", "/dashboard/resumen"), ("cliente", "GET", "/tarifas/x"),
    ("cliente", "GET", "/costos-ruta"), ("cliente", "POST", "/facturas/cerrar-periodo"), ("cliente", "POST", "/etl/ejecutar"),
    ("cliente", "GET", "/estado"), ("cliente", "GET", "/programas"), ("cliente", "GET", "/dashboard/ingresos/mensual"),
    ("operador", "GET", "/dashboard/ingresos/anual"),
    ("cliente", "POST", "/pagos/abc/reembolsar"), ("operador", "POST", "/pagos/abc/reembolsar"),
    ("gestor_flota", "POST", "/pagos/abc/reembolsar"), ("cliente", "GET", "/pagos/por-reembolsar"),
    ("operador", "GET", "/pagos/por-reembolsar"), ("gestor_flota", "GET", "/pagos/por-reembolsar"), ("gestor_flota", "GET", "/dashboard/ingresos/pedidos"),
    ("operador", "GET", "/usuarios"), ("operador", "POST", "/vehiculos"), ("operador", "PATCH", "/vehiculos/x/estado"),
    ("operador", "POST", "/conductores"), ("operador", "POST", "/intervenciones"), ("operador", "POST", "/envios/abc/cancelar"),
    ("operador", "PATCH", "/envios/abc/reprogramar"), ("operador", "GET", "/facturas"), ("operador", "GET", "/tarifas/x"),
    ("operador", "GET", "/dashboard/resumen"), ("operador", "GET", "/dashboard/utilizacion-flota"), ("operador", "POST", "/etl/ejecutar"),
    ("operador", "GET", "/estado"), ("operador", "GET", "/facturas-pedido"),
    ("gestor_flota", "GET", "/pagos"), ("gestor_flota", "GET", "/cotizaciones"), ("gestor_flota", "GET", "/facturas-pedido"),
    ("gestor_flota", "GET", "/usuarios"), ("gestor_flota", "POST", "/clientes"), ("gestor_flota", "GET", "/clientes"),
    ("gestor_flota", "POST", "/envios"), ("gestor_flota", "POST", "/envios/abc/prueba-entrega"), ("gestor_flota", "GET", "/declaraciones"),
    ("gestor_flota", "GET", "/facturas"), ("gestor_flota", "GET", "/dashboard/resumen"), ("gestor_flota", "POST", "/etl/ejecutar"),
    ("gestor_flota", "GET", "/estado"), ("gestor_flota", "POST", "/viabilidad"),
]


@pytest.mark.parametrize("rol,metodo,ruta", PERMITIDO)
def test_rol_permitido(gw, rol, metodo, ruta):
    r = gw.request(metodo, "/api/v1" + ruta, headers=auth(rol), json={} if metodo != "GET" else None)
    assert r.status_code not in (401, 403), f"{rol} {metodo} {ruta} -> {r.status_code} {r.text}"


@pytest.mark.parametrize("rol,metodo,ruta", DENEGADO)
def test_rol_denegado(gw, rol, metodo, ruta):
    n = len(recibidas)
    r = gw.request(metodo, "/api/v1" + ruta, headers=auth(rol), json={} if metodo != "GET" else None)
    assert r.status_code == 403, f"{rol} {metodo} {ruta} -> {r.status_code}"
    assert r.json()["detail"]["codigo"] == "SIN_PERMISO"
    assert len(recibidas) == n, "la petición denegada no debe llegar al microservicio"


# ---------- reglas especiales del cliente ----------

def test_facturas_del_cliente_se_filtran_por_su_cliente_id(gw):
    gw.get(f"/api/v1/facturas?cliente_id={CLIENTE_B}&periodo=2026-10", headers=auth("cliente"))
    q = dict(recibidas[0].url.params.multi_items())
    assert q["cliente_id"] == CLIENTE_A and q["periodo"] == "2026-10"
    assert len(recibidas[0].url.params.get_list("cliente_id")) == 1


@pytest.mark.parametrize("ruta", ["/cotizaciones", "/pagos", "/facturas-pedido"])
def test_cobros_del_cliente_se_filtran_y_llegan_a_billing(gw, ruta):
    gw.get(f"/api/v1{ruta}?cliente_id={CLIENTE_B}", headers=auth("cliente"))
    assert recibidas[0].url.host == "billing.test" and recibidas[0].url.path.rstrip("/") == ruta
    assert recibidas[0].url.params.get_list("cliente_id") == [CLIENTE_A]
    assert recibidas[0].headers["x-cliente-id"] == CLIENTE_A


def test_cotizar_llega_a_shipment_para_cliente_operador_y_administrador(gw):
    for rol in ("cliente", "operador", "administrador"):
        assert gw.post("/api/v1/envios/cotizar", json={}, headers=auth(rol)).status_code == 200
        assert recibidas[-1].url.host == "shipment.test" and recibidas[-1].url.path.rstrip("/") == "/envios/cotizar"


def test_facturas_del_administrador_no_se_filtran(gw):
    gw.get(f"/api/v1/facturas?cliente_id={CLIENTE_B}", headers=auth("administrador"))
    assert recibidas[0].url.params["cliente_id"] == CLIENTE_B


def test_preferencias_solo_las_propias(gw):
    assert gw.get(f"/api/v1/preferencias/{CLIENTE_A}", headers=auth("cliente")).status_code == 200
    r = gw.get(f"/api/v1/preferencias/{CLIENTE_B}", headers=auth("cliente"))
    assert r.status_code == 403
    assert gw.post(f"/api/v1/preferencias/{CLIENTE_B}", json={}, headers=auth("administrador")).status_code == 200


def test_cuenta_cliente_sin_cliente_id_en_token_es_403(gw):
    h = {"Authorization": f"Bearer {token('cliente', None)}"}
    assert gw.get("/api/v1/envios", headers=h).status_code == 403


# ---------- documentación ----------

def test_openapi_declara_bearer(gw):
    r = gw.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert spec["security"] == [{"bearerAuth": []}]


# ---------- seguimiento en tiempo real para el cliente ----------

ENVIO = "33333333-3333-3333-3333-333333333333"
RUTAS_CLIENTE = [f"/seguimiento/cliente/envio/{ENVIO}", f"/seguimiento/cliente/envio/{ENVIO}/trazado",
                 f"/seguimiento/cliente/envio/{ENVIO}/recorrido"]


@pytest.mark.parametrize("ruta", RUTAS_CLIENTE)
def test_el_cliente_sigue_su_envio_por_el_gateway_con_su_identidad(gw, ruta):
    h = {**auth("cliente"), "X-User-Rol": "administrador", "X-Cliente-Id": CLIENTE_B}     # identidad falsa desde afuera
    r = gw.get(f"/api/v1{ruta}?cliente_id={CLIENTE_B}&limite=50", headers=h)
    assert r.status_code == 200
    llegada = recibidas[-1]
    assert llegada.url.host == "tracking.test" and llegada.url.path == ruta
    assert llegada.headers["x-user-rol"] == "cliente" and llegada.headers["x-cliente-id"] == CLIENTE_A
    assert "authorization" not in llegada.headers


@pytest.mark.parametrize("rol", ["operador", "gestor_flota", "administrador"])
@pytest.mark.parametrize("ruta", RUTAS_CLIENTE)
def test_la_ruta_del_cliente_es_solo_del_cliente(gw, rol, ruta):
    n = len(recibidas)
    r = gw.get(f"/api/v1{ruta}", headers=auth(rol))
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "SIN_PERMISO" and len(recibidas) == n


def test_sin_token_el_seguimiento_del_cliente_es_401(gw):
    assert gw.get(f"/api/v1/seguimiento/cliente/envio/{ENVIO}").status_code == 401


@pytest.mark.parametrize("ruta", [
    "/seguimiento/flota", f"/seguimiento/vehiculo/{ENVIO}", "/seguimiento/codigo/ENV-00000001", f"/seguimiento/envio/{ENVIO}",
    f"/seguimiento/envio/{ENVIO}/trazado", f"/seguimiento/envio/{ENVIO}/recorrido",
    "/telemetria", "/telemetria/ultima", "/simulaciones", f"/simulaciones/{ENVIO}",
    # intentos de colarse por la ruta del cliente
    "/seguimiento/cliente/flota", "/seguimiento/cliente/envio", "/seguimiento/cliente/envio/",
    "/seguimiento/cliente/envio/no-es-uuid", f"/seguimiento/cliente/envio/{ENVIO}/otra", f"/seguimiento/cliente/envio/{ENVIO}/../../flota",
    "/seguimiento/cliente/envio/../../flota", f"/seguimiento/cliente/envio/{ENVIO}/trazado/extra", "/seguimiento/cliente/envio/%2e%2e/flota",
    f"/seguimiento//cliente/envio/{ENVIO}",
])
def test_el_cliente_sigue_sin_poder_ver_la_flota_vehiculos_ni_telemetria(gw, ruta):
    n = len(recibidas)
    r = gw.get("/api/v1" + ruta, headers=auth("cliente"))
    assert r.status_code in (403, 404), f"{ruta} -> {r.status_code}"
    assert len(recibidas) == n, "no debe llegar nada a Tracking"


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
def test_el_seguimiento_del_cliente_es_solo_lectura(gw, metodo):
    n = len(recibidas)
    r = gw.request(metodo, f"/api/v1/seguimiento/cliente/envio/{ENVIO}", headers=auth("cliente"), json={})
    assert r.status_code in (403, 405) and len(recibidas) == n


def test_el_personal_conserva_el_seguimiento_de_siempre(gw):
    for rol in ("operador", "gestor_flota", "administrador"):
        for ruta in ("/seguimiento/flota", f"/seguimiento/envio/{ENVIO}", f"/seguimiento/vehiculo/{ENVIO}", "/telemetria", "/simulaciones"):
            r = gw.get("/api/v1" + ruta, headers=auth(rol))
            assert r.status_code == 200, f"{rol} {ruta} -> {r.status_code}"


def test_una_ruta_con_salto_de_linea_final_no_coincide_con_ninguna_regla():
    from app.permisos import buscar_regla
    assert buscar_regla("GET", f"/seguimiento/cliente/envio/{ENVIO}") is not None
    assert buscar_regla("GET", f"/seguimiento/cliente/envio/{ENVIO}\n") is None
    assert buscar_regla("GET", "/envios\n") is None


# ---------- ubicación base de los vehículos ----------

VEH = "44444444-4444-4444-4444-444444444444"


@pytest.mark.parametrize("rol", ["gestor_flota", "administrador"])
def test_gestor_y_admin_fijan_la_ubicacion_de_un_vehiculo_por_el_gateway(gw, rol):
    r = gw.put(f"/api/v1/vehiculos/{VEH}/ubicacion", json={"latitud": 4.7, "longitud": -74.0, "codigo_pais": "CO"}, headers=auth(rol))
    assert r.status_code == 200
    assert recibidas[-1].method == "PUT" and recibidas[-1].url.host == "fleet.test"
    assert recibidas[-1].url.path == f"/vehiculos/{VEH}/ubicacion"


@pytest.mark.parametrize("rol", ["cliente", "operador"])
def test_cliente_y_operador_no_pueden_fijar_la_ubicacion_de_un_vehiculo(gw, rol):
    n = len(recibidas)
    r = gw.put(f"/api/v1/vehiculos/{VEH}/ubicacion", json={}, headers=auth(rol))
    assert r.status_code == 403 and len(recibidas) == n


def test_sin_token_no_se_fija_la_ubicacion(gw):
    assert gw.put(f"/api/v1/vehiculos/{VEH}/ubicacion", json={}).status_code == 401
