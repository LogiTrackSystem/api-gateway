"""Calentamiento de microservicios al arrancar el gateway: reintentos, paralelismo, cabecera interna y que no bloquee."""
import asyncio
import contextlib
import importlib
import logging
import time

import httpx
from fastapi.testclient import TestClient


class _Diferido:
    """Importa el módulo al usarlo, no al cargar este archivo. test_permisos.py fija variables de entorno
    (JWT_SECRET y *_SERVICE_URL) cuando se importa; si aquí se importara app.config antes, la configuración
    quedaría leída sin esas variables y fallarían las pruebas de permisos."""

    def __init__(self, nombre: str):
        self._nombre = nombre

    def __getattr__(self, atributo):
        # pytest sondea los objetos de cada módulo al recolectar (__test__, pytestmark...): eso no debe importar nada
        if atributo.startswith("_") or atributo == "pytestmark":
            raise AttributeError(atributo)
        return getattr(importlib.import_module(self._nombre), atributo)


calentamiento = _Diferido("app.calentamiento")
config = _Diferido("app.config")
interno = _Diferido("app.interno")


def config_calentamiento():
    return config.config_calentamiento()


def urls_de_salud(*args, **kwargs):
    return config.urls_de_salud(*args, **kwargs)


def cabeceras_internas():
    return interno.cabeceras_internas()


def _config(**cambios):
    base = dict(activo=True, intentos=4, pausa_s=0.0, timeout_s=5.0, intervalo_min=0.0, solo=frozenset())
    base.update(cambios)
    return config.ConfigCalentamiento(**base)


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"status": "ok"})


def _cliente(manejador, **kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(manejador), **kw)


def _correr(corrutina):
    return asyncio.run(corrutina)


# ---------- configuración ----------
def test_urls_de_salud_usa_solo_los_servicios_configurados():
    urls = urls_de_salud({"fleet": "http://f:8000", "billing": None, "tracking": "http://t:8004"})
    assert urls == {"fleet": "http://f:8000/health", "tracking": "http://t:8004/health"}


def test_urls_de_salud_puede_filtrar_por_nombre():
    urls = urls_de_salud({"fleet": "http://f", "tracking": "http://t"}, frozenset({"tracking"}))
    assert urls == {"tracking": "http://t/health"}


def test_configuracion_por_defecto(monkeypatch):
    for v in ("WARMUP_ACTIVO", "WARMUP_INTENTOS", "WARMUP_PAUSA_S", "WARMUP_TIMEOUT_S", "WARMUP_INTERVALO_MIN", "WARMUP_SERVICIOS"):
        monkeypatch.delenv(v, raising=False)
    c = config_calentamiento()
    assert (c.activo, c.intentos, c.pausa_s, c.timeout_s, c.intervalo_min, c.solo) == (True, 0, 5.0, 30.0, 0.0, frozenset())


def test_configuracion_lee_el_entorno_y_tolera_valores_invalidos(monkeypatch):
    monkeypatch.setenv("WARMUP_ACTIVO", "false")
    monkeypatch.setenv("WARMUP_INTENTOS", "-4")         # mínimo 0 (= sin límite)
    monkeypatch.setenv("WARMUP_PAUSA_S", "no-es-numero")  # cae al valor por defecto
    monkeypatch.setenv("WARMUP_SERVICIOS", "Fleet, tracking ,")
    c = config_calentamiento()
    assert c.activo is False and c.intentos == 0 and c.pausa_s == 5.0
    assert c.solo == frozenset({"fleet", "tracking"})


def test_con_intentos_ilimitados_la_pausa_nunca_baja_de_un_segundo(monkeypatch):
    monkeypatch.setenv("WARMUP_INTENTOS", "0")
    monkeypatch.setenv("WARMUP_PAUSA_S", "0")
    assert config_calentamiento().pausa_s == 1.0


def test_con_intentos_limitados_se_respeta_la_pausa_pedida(monkeypatch):
    monkeypatch.setenv("WARMUP_INTENTOS", "3")
    monkeypatch.setenv("WARMUP_PAUSA_S", "0")
    c = config_calentamiento()
    assert c.intentos == 3 and c.pausa_s == 0.0


# ---------- un servicio ----------
def test_responde_al_primer_intento_y_envia_la_clave_interna(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-123")
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append((req.url.path, req.headers.get("x-internal-key")))
        return httpx.Response(200, json={"status": "ok"})

    async def prueba():
        async with _cliente(manejador, headers=cabeceras_internas()) as c:
            return await calentamiento.calentar_servicio(c, "fleet", "http://f/health", intentos=3, pausa_s=0)

    r = _correr(prueba())
    assert r.activo and r.intentos == 1 and r.detalle == "HTTP 200"
    assert vistas == [("/health", "clave-123")]


def test_reintenta_tras_errores_de_conexion_hasta_que_despierta():
    llamadas = {"n": 0}

    def manejador(req):
        llamadas["n"] += 1
        if llamadas["n"] <= 2:
            raise httpx.ConnectTimeout("dormido")
        return _ok()

    async def prueba():
        async with _cliente(manejador) as c:
            return await calentamiento.calentar_servicio(c, "routing", "http://r/health", intentos=5, pausa_s=0)

    r = _correr(prueba())
    assert r.activo and r.intentos == 3 and llamadas["n"] == 3


def test_reintenta_los_5xx_mientras_render_levanta_el_contenedor():
    respuestas = iter([502, 503, 200])
    r = _correr(_una(lambda req: httpx.Response(next(respuestas), json={"status": "ok"}), intentos=5))
    assert r.activo and r.intentos == 3


def test_un_4xx_no_se_reintenta_porque_el_servicio_ya_esta_despierto():
    llamadas = {"n": 0}

    def manejador(req):
        llamadas["n"] += 1
        return httpx.Response(404)

    r = _correr(_una(manejador, intentos=5))
    assert r.activo and r.intentos == 1 and r.detalle == "HTTP 404" and llamadas["n"] == 1


def test_un_200_que_no_es_json_se_sigue_reintentando():
    # la plataforma puede contestar 200 con una página HTML de "arrancando" antes de que el servicio responda
    respuestas = iter([httpx.Response(200, text="<html>Starting</html>", headers={"content-type": "text/html"}),
                       httpx.Response(200, text="<html>Starting</html>", headers={"content-type": "text/html"}),
                       _ok()])
    r = _correr(_una(lambda req: next(respuestas), intentos=5))
    assert r.activo and r.intentos == 3 and r.detalle == "HTTP 200"


def test_un_429_se_reintenta_porque_no_es_error_de_ruta():
    respuestas = iter([429, 200])
    r = _correr(_una(lambda req: httpx.Response(next(respuestas), json={}), intentos=5))
    assert r.activo and r.intentos == 2


def test_sin_limite_de_intentos_insiste_hasta_que_el_servicio_despierta():
    llamadas = {"n": 0}

    def manejador(req):
        llamadas["n"] += 1
        if llamadas["n"] <= 25:  # mucho más de los 5 intentos de antes: simula un arranque en frío largo
            raise httpx.ReadTimeout("dormido")
        return _ok()

    r = _correr(_una(manejador, intentos=0))
    assert r.activo and r.intentos == 26 and llamadas["n"] == 26


def test_sin_limite_alterna_5xx_y_timeouts_hasta_despertar():
    pasos = iter([502] * 4 + ["timeout"] * 4 + [503] * 3 + [200])

    def manejador(req):
        paso = next(pasos)
        if paso == "timeout":
            raise httpx.ConnectTimeout("dormido")
        return httpx.Response(paso, json={"status": "ok"})

    r = _correr(_una(manejador, intentos=0))
    assert r.activo and r.intentos == 12


def test_sin_limite_la_tarea_solo_termina_si_se_cancela():
    async def prueba():
        def manejador(req):
            raise httpx.ConnectError("caído")

        async with _cliente(manejador) as c:
            tarea = asyncio.create_task(
                calentamiento.calentar_servicio(c, "x", "http://x/health", intentos=0, pausa_s=0.01))
            await asyncio.sleep(0.2)
            sigue = not tarea.done()
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea
            return sigue, tarea.cancelled()

    assert _correr(prueba()) == (True, True)


def test_el_estado_pasa_de_calentando_a_activo():
    estado = {}
    vistos = []

    def manejador(req):
        vistos.append(dict(estado))
        return _ok()

    async def prueba():
        async with _cliente(manejador) as c:
            return await calentamiento.calentar_servicio(c, "fleet", "http://f/health", intentos=2, pausa_s=0, estado=estado)

    _correr(prueba())
    assert vistos == [{"fleet": "calentando"}] and estado == {"fleet": "activo"}


def test_el_resumen_describe_el_progreso():
    r = calentamiento.resumen
    assert r(None) == {"estado": "desactivado"}
    assert r({"a": "activo"}, activado=False) == {"estado": "desactivado"}
    assert r({}) == {"estado": "sin_servicios", "activos": 0, "total": 0}
    assert r({"a": "activo", "b": "calentando"}) == {"estado": "en_curso", "activos": 1, "total": 2}
    assert r({"a": "activo", "b": "activo"}) == {"estado": "completo", "activos": 2, "total": 2}
    assert r({"a": "activo", "b": "descartado"}) == {"estado": "incompleto", "activos": 1, "total": 2}


def test_si_nunca_responde_se_descarta_tras_los_intentos():
    def manejador(req):
        raise httpx.ConnectError("sin conexión")

    r = _correr(_una(manejador, intentos=3))
    assert not r.activo and r.intentos == 3 and "ConnectError" in r.detalle


async def _una(manejador, intentos):
    async with _cliente(manejador) as c:
        return await calentamiento.calentar_servicio(c, "x", "http://x/health", intentos=intentos, pausa_s=0)


# ---------- todos los servicios ----------
def test_los_servicios_se_calientan_en_paralelo():
    async def manejador(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return _ok()

    servicios = {f"s{i}": f"http://s{i}.test" for i in range(5)}

    async def prueba():
        async with _cliente(manejador) as c:
            inicio = time.perf_counter()
            res = await calentamiento.ejecutar(_config(), servicios, c)
            return res, time.perf_counter() - inicio

    resultados, segundos = _correr(prueba())
    assert len(resultados) == 5 and all(r.activo for r in resultados)
    assert segundos < 1.0  # en serie serían ~1,5 s


def test_un_servicio_caido_no_impide_calentar_los_demas():
    def manejador(req: httpx.Request) -> httpx.Response:
        if req.url.host == "malo.test":
            raise httpx.ConnectTimeout("dormido")
        return _ok()

    servicios = {"bueno": "http://bueno.test", "malo": "http://malo.test"}

    async def prueba():
        async with _cliente(manejador) as c:
            return await calentamiento.ejecutar(_config(intentos=2), servicios, c)

    por_nombre = {r.servicio: r for r in _correr(prueba())}
    assert por_nombre["bueno"].activo and not por_nombre["malo"].activo and por_nombre["malo"].intentos == 2


def test_sin_servicios_configurados_no_hace_nada():
    assert _correr(calentamiento.ejecutar(_config(), {})) == []


def test_el_cliente_propio_lleva_la_clave_interna(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-xyz")
    capturado = {}
    original = httpx.AsyncClient

    def falso(*args, **kwargs):
        capturado.update(kwargs)
        return original(transport=httpx.MockTransport(lambda r: _ok()), **kwargs)

    monkeypatch.setattr(calentamiento.httpx, "AsyncClient", falso)
    _correr(calentamiento.ejecutar(_config(), {"fleet": "http://f.test"}))
    assert capturado["headers"] == {"X-Internal-Key": "clave-xyz"}


def test_los_logs_siguen_el_estado_de_cada_servicio(caplog):
    def manejador(req):
        return _ok()

    with caplog.at_level(logging.INFO, logger="logitrack.warmup"):
        _correr(_todos(manejador, {"fleet": "http://f.test"}))
    texto = caplog.text
    assert "Enviando ping de calentamiento a fleet" in texto
    assert "SUCCESS" in texto and "Servicio fleet activo" in texto


async def _todos(manejador, servicios):
    async with _cliente(manejador) as c:
        return await calentamiento.ejecutar(_config(), servicios, c)


# ---------- que no bloquee el arranque ----------
def test_iniciar_regresa_de_inmediato_aunque_el_servicio_tarde():
    async def prueba():
        liberar = asyncio.Event()

        async def manejador(req):
            await liberar.wait()  # el servicio "duerme" hasta que se libere
            return _ok()

        async with _cliente(manejador) as c:
            inicio = time.perf_counter()
            tarea = calentamiento.iniciar(_config(), {"fleet": "http://f.test"}, c)
            regreso = time.perf_counter() - inicio
            await asyncio.sleep(0.05)
            sigue_corriendo = not tarea.done()
            liberar.set()
            resultados = await tarea
            return regreso, sigue_corriendo, resultados

    regreso, sigue, resultados = _correr(prueba())
    assert regreso < 0.05 and sigue
    assert resultados[0].activo


def test_desactivado_no_lanza_nada():
    async def prueba():
        return calentamiento.iniciar(_config(activo=False), {"fleet": "http://f.test"})

    assert _correr(prueba()) is None


def test_detener_cancela_una_tarea_en_curso():
    async def prueba():
        async def manejador(req):
            await asyncio.sleep(30)
            return _ok()

        async with _cliente(manejador) as c:
            tarea = calentamiento.iniciar(_config(), {"fleet": "http://f.test"}, c)
            await asyncio.sleep(0.05)
            await calentamiento.detener(tarea)
            return tarea.cancelled() or tarea.done()

    assert _correr(prueba())


def test_el_gateway_arranca_y_responde_aunque_el_calentamiento_siga_en_curso(monkeypatch):
    # un servicio inalcanzable (puerto cerrado) que se reintenta sin fin: el gateway no debe esperarlo
    monkeypatch.setattr("app.calentamiento.SERVICIOS", {"fleet": "http://127.0.0.1:9"})
    monkeypatch.setenv("WARMUP_ACTIVO", "true")
    monkeypatch.setenv("WARMUP_INTENTOS", "0")
    monkeypatch.setenv("WARMUP_PAUSA_S", "10")
    from app.main import app

    inicio = time.perf_counter()
    with TestClient(app) as cliente:
        assert isinstance(app.state.warmup, asyncio.Task)
        cuerpo = cliente.get("/health").json()
        assert cuerpo["status"] == "ok" and cuerpo["service"] == "api-gateway"
        assert cuerpo["calentamiento"]["total"] == 1  # fleet
    assert time.perf_counter() - inicio < 5  # al apagar se cancela la tarea, no se espera la pausa de 10 s


def test_health_indica_calentamiento_desactivado_por_defecto():
    from app.main import app

    with TestClient(app) as cliente:  # conftest fija WARMUP_ACTIVO=false
        assert cliente.get("/health").json()["calentamiento"] == {"estado": "desactivado"}
