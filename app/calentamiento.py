"""Calentamiento ("warm-up") de los microservicios cuando el gateway arranca.

Render (plan gratis) duerme cada servicio tras ~15 minutos sin peticiones y puede tardar hasta 2 minutos en
volver a levantarlo. Si la primera petición real de un usuario cae sobre un servicio dormido, falla
(timeout o 502). Para evitarlo, apenas arranca el gateway lanzamos una tarea en segundo plano que le hace
ping a /health de todos los servicios a la vez y NO se rinde: reintenta cada servicio, sin límite por defecto,
hasta que responde. Así nadie tiene que ir abriendo los servicios uno por uno.

- No bloquea el arranque: se lanza con asyncio.create_task dentro del lifespan.
- Usa su propio httpx.AsyncClient con la clave interna (X-Internal-Key), igual que el resto de llamadas
  del gateway a los servicios.
- Las URLs salen de config.SERVICIOS (las variables *_SERVICE_URL), sin duplicar listas.
- Nunca levanta excepciones hacia afuera: lo que no responde solo queda registrado en el log.
- Su progreso se puede consultar en el /health del gateway (campo "calentamiento").

Comprobación periódica (WARMUP_INTERVALO_MIN > 0, 5 minutos por defecto): después del calentamiento inicial cada
servicio tiene SU PROPIA tarea que le hace GET /health cada N minutos. Son independientes: un servicio caído solo
detiene a su propia tarea, nunca a las demás, y sus reintentos están acotados (WARMUP_INTENTOS_PERIODICOS).
Las comprobaciones se reparten en el tiempo (cada servicio con su desfase) para no hacer 9 peticiones a la vez.
El /health de cada microservicio es estático (no toca base de datos ni RabbitMQ): no tiene efectos secundarios.
OJO: comprobar la salud NO garantiza que Render mantenga despierto un servicio gratis (ver README).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

import httpx

from .config import SERVICIOS, ConfigCalentamiento, config_calentamiento, urls_de_salud
from .interno import cabeceras_internas

NIVEL_SUCCESS = 25  # entre INFO (20) y WARNING (30)
logging.addLevelName(NIVEL_SUCCESS, "SUCCESS")
log = logging.getLogger("logitrack.warmup")

CALENTANDO, ACTIVO, DESCARTADO = "calentando", "activo", "descartado"
# Códigos 4xx que significan "vuelve a intentar" y no "la ruta está mal": 408 timeout, 425 too early, 429 límite de tasa
REINTENTABLES_4XX = frozenset({408, 425, 429})


@dataclass(frozen=True)
class ResultadoCalentamiento:
    servicio: str
    activo: bool      # True si el servicio respondió (aunque sea con un 4xx: está despierto)
    intentos: int     # intentos que hizo
    ms: int           # milisegundos desde el primer intento hasta el resultado
    detalle: str      # "HTTP 200", último error, etc.


def _preparar_logging() -> None:
    """uvicorn solo configura sus propios loggers: sin esto los INFO de este módulo no saldrían en consola.
    Si la aplicación ya tiene un logging configurado (o pytest), no se toca nada."""
    if log.handlers or logging.getLogger().handlers:
        return
    manejador = logging.StreamHandler()
    manejador.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(manejador)
    log.setLevel(logging.INFO)
    log.propagate = False


def _descripcion(exc: Exception) -> str:
    texto = str(exc)
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


def _hablar(n: int) -> bool:
    """Con reintentos sin límite, un servicio caído de verdad llenaría el log: se escriben los primeros
    intentos y después uno de cada cinco."""
    return n <= 3 or n % 5 == 0


def _es_json(resp: httpx.Response) -> bool:
    return "json" in resp.headers.get("content-type", "").lower()


async def calentar_servicio(
    cliente: httpx.AsyncClient,
    servicio: str,
    url: str,
    *,
    intentos: int,
    pausa_s: float,
    estado: dict[str, str] | None = None,
    periodico: bool = False,
) -> ResultadoCalentamiento:
    """Hace GET a `url` con `pausa_s` segundos entre intentos. `intentos` = 0 significa sin límite:
    se repite hasta que el servicio responda (o hasta que la tarea se cancele).
    `periodico=True` (comprobaciones de rutina): los mensajes de éxito y de cada intento pasan a DEBUG para no llenar el log."""
    inicio = time.perf_counter()
    limite = f"/{intentos}" if intentos else ""
    detalle = "sin intentos"
    n = 0
    if estado is not None:
        estado[servicio] = CALENTANDO
    while not intentos or n < intentos:
        n += 1
        if _hablar(n):
            log.log(logging.DEBUG if periodico else logging.INFO,
                    "Enviando ping de calentamiento a %s (intento %d%s): %s", servicio, n, limite, url)
        try:
            resp = await cliente.get(url)
        except Exception as exc:  # RequestError, timeouts, DNS/TLS... (CancelledError no entra aquí)
            detalle = _descripcion(exc)
            if _hablar(n):
                log.warning("Servicio %s aún no responde (intento %d%s): %s", servicio, n, limite, detalle)
        else:
            ms = round((time.perf_counter() - inicio) * 1000)
            detalle = f"HTTP {resp.status_code}"
            if resp.status_code == 200 and _es_json(resp):
                log.log(logging.DEBUG if periodico else NIVEL_SUCCESS,
                        "Servicio %s activo (%d ms, intento %d%s)", servicio, ms, n, limite)
                if estado is not None:
                    estado[servicio] = ACTIVO
                return ResultadoCalentamiento(servicio, True, n, ms, detalle)
            if resp.status_code == 200:
                # 200 que no es JSON: probablemente la página de "arrancando" de la plataforma, no el servicio
                detalle = "HTTP 200 (no es JSON: el servicio aún no responde por sí mismo)"
                if _hablar(n):
                    log.warning("Servicio %s: %s (intento %d%s)", servicio, detalle, n, limite)
            elif 400 <= resp.status_code < 500 and resp.status_code not in REINTENTABLES_4XX:
                # Respondió: el contenedor ya está despierto. Reintentar no arregla un 4xx (ruta o clave mal puestas).
                log.warning("Servicio %s despierto, pero /health respondió %s; no se reintenta", servicio, detalle)
                if estado is not None:
                    estado[servicio] = ACTIVO
                return ResultadoCalentamiento(servicio, True, n, ms, detalle)
            elif _hablar(n):
                # 5xx (502/503 mientras Render levanta el contenedor) o 4xx reintentable
                log.warning("Servicio %s respondió %s (intento %d%s); sigue levantando", servicio, detalle, n, limite)
        if not intentos or n < intentos:
            await asyncio.sleep(pausa_s)
    ms = round((time.perf_counter() - inicio) * 1000)
    log.error("Servicio %s no respondió tras %d intento(s): %s", servicio, n, detalle)
    if estado is not None:
        estado[servicio] = DESCARTADO
    return ResultadoCalentamiento(servicio, False, n, ms, detalle)


def resumen(estado: dict[str, str] | None, activado: bool = True) -> dict:
    """Resumen para /health: {"estado": "desactivado" | "sin_servicios" | "en_curso" | "completo" | "incompleto", ...}."""
    if estado is None or not activado:
        return {"estado": "desactivado"}
    total = len(estado)
    activos = sum(1 for v in estado.values() if v == ACTIVO)
    if total == 0:
        return {"estado": "sin_servicios", "activos": 0, "total": 0}
    if any(v == CALENTANDO for v in estado.values()):
        situacion = "en_curso"
    else:
        situacion = "completo" if activos == total else "incompleto"
    return {"estado": situacion, "activos": activos, "total": total}


HORA_S = 3600.0
# Con comprobación periódica, "reintentar sin límite" al arrancar convertiría a un servicio caído de verdad en una
# petición cada pausa_s para siempre. Se acota: pasados estos intentos el servicio pasa al ritmo normal (cada N min).
INTENTOS_ARRANQUE_PERIODICO = 24


async def _vigilar_servicio(
    cliente: httpx.AsyncClient,
    nombre: str,
    url: str,
    config: ConfigCalentamiento,
    estado: dict[str, str] | None,
    desfase_s: float,
    progreso: dict,
) -> ResultadoCalentamiento:
    """Calentamiento inicial de UN servicio y, si hay intervalo, su comprobación periódica. Cada servicio corre en
    su propia corrutina: lo que le pase a uno no afecta a los demás. Con intervalo no termina hasta que se cancele."""
    intentos = config.intentos
    if config.intervalo_min > 0 and intentos == 0:
        intentos = INTENTOS_ARRANQUE_PERIODICO
    resultado = await calentar_servicio(cliente, nombre, url, intentos=intentos, pausa_s=config.pausa_s, estado=estado)
    progreso["pendientes"] -= 1
    progreso["activos"] += int(resultado.activo)
    if progreso["pendientes"] == 0:   # el último servicio en terminar el calentamiento inicial cierra el resumen
        nivel = NIVEL_SUCCESS if progreso["activos"] == progreso["total"] else logging.WARNING
        log.log(nivel, "Calentamiento terminado: %d/%d servicio(s) activos", progreso["activos"], progreso["total"])
    if config.intervalo_min <= 0:
        return resultado
    espera_s = config.intervalo_min * 60.0
    activo = resultado.activo
    comprobaciones = fallos = 0
    ultimo_informe = time.monotonic()
    await asyncio.sleep(espera_s + desfase_s)   # el desfase reparte las 9 comprobaciones dentro del intervalo
    while True:
        r = await calentar_servicio(
            cliente, nombre, url, intentos=max(1, config.intentos_periodicos), pausa_s=config.pausa_s, periodico=True)
        comprobaciones += 1
        fallos += 0 if r.activo else 1
        if estado is not None:
            estado[nombre] = ACTIVO if r.activo else DESCARTADO
        if r.activo and not activo:
            log.log(NIVEL_SUCCESS, "Servicio %s volvió a responder (%d ms)", nombre, r.ms)
        elif not r.activo and activo:
            log.warning("Servicio %s dejó de responder: %s", nombre, r.detalle)
        activo = r.activo
        if time.monotonic() - ultimo_informe >= HORA_S:
            # Un resumen por servicio y hora: prueba de que las comprobaciones corren, sin llenar el log
            log.info("Health check periódico de %s: %d comprobación(es) y %d fallo(s) en la última hora (ahora: %s)",
                     nombre, comprobaciones, fallos, "activo" if activo else r.detalle)
            comprobaciones = fallos = 0
            ultimo_informe = time.monotonic()
        await asyncio.sleep(espera_s)


async def ejecutar(
    config: ConfigCalentamiento | None = None,
    servicios: dict[str, str | None] | None = None,
    cliente: httpx.AsyncClient | None = None,
    estado: dict[str, str] | None = None,
) -> list[ResultadoCalentamiento]:
    """Calienta todos los servicios en paralelo. Con WARMUP_INTERVALO_MIN > 0 cada servicio sigue comprobándose
    cada N minutos (no regresa hasta que se cancele la tarea); en otro caso termina cuando todos respondieron."""
    _preparar_logging()
    config = config or config_calentamiento()
    urls = urls_de_salud(SERVICIOS if servicios is None else servicios, config.solo)
    if not urls:
        log.info("Calentamiento omitido: no hay microservicios configurados (*_SERVICE_URL)")
        return []

    propio = cliente is None
    if propio:
        cliente = httpx.AsyncClient(
            headers=cabeceras_internas(),
            timeout=httpx.Timeout(config.timeout_s),
            follow_redirects=True,
        )
    try:
        periodico = config.intervalo_min > 0
        if periodico and config.intervalo_min >= 15:
            log.warning("WARMUP_INTERVALO_MIN=%s: Render gratis duerme tras ~15 min sin tráfico; con este intervalo "
                        "los servicios pueden dormirse entre comprobaciones", config.intervalo_min)
        log.info(
            "Iniciando calentamiento de %d microservicio(s): %s (%s)%s", len(urls), ", ".join(urls),
            f"hasta {config.intentos} intentos cada uno" if config.intentos else "reintentando hasta que respondan",
            f"; después, comprobación cada {config.intervalo_min:g} min" if periodico else "",
        )
        if estado is not None:
            estado.update({nombre: CALENTANDO for nombre in urls})
        separacion = config.intervalo_min * 60.0 / len(urls) if periodico else 0.0
        progreso = {"pendientes": len(urls), "activos": 0, "total": len(urls)}
        tareas = [
            asyncio.ensure_future(_vigilar_servicio(cliente, nombre, url, config, estado, i * separacion, progreso))
            for i, (nombre, url) in enumerate(urls.items())
        ]
        try:
            resultados = list(await asyncio.gather(*tareas))
        except BaseException:
            for t in tareas:   # al cancelar (apagado del gateway) no queda ninguna comprobación suelta
                t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            raise
        return resultados
    finally:
        if propio:
            await cliente.aclose()


async def _sin_excepciones(corrutina) -> list[ResultadoCalentamiento]:
    """La tarea corre sola (nadie hace await de su resultado): una excepción inesperada solo se registra."""
    try:
        return await corrutina
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("El calentamiento de microservicios terminó con un error inesperado")
        return []


_TAREA: asyncio.Task | None = None   # la única tarea de comprobación de este proceso


def iniciar(
    config: ConfigCalentamiento | None = None,
    servicios: dict[str, str | None] | None = None,
    cliente: httpx.AsyncClient | None = None,
    estado: dict[str, str] | None = None,
) -> asyncio.Task[list[ResultadoCalentamiento]] | None:
    """Lanza el calentamiento en segundo plano y devuelve de inmediato (fire-and-forget).
    Debe llamarse con el event loop corriendo (dentro del lifespan). Guarda la tarea: si nadie
    mantiene una referencia, Python puede recolectarla antes de que termine."""
    config = config or config_calentamiento()
    if not config.activo:
        _preparar_logging()
        log.info("Calentamiento de microservicios desactivado (WARMUP_ACTIVO)")
        return None
    global _TAREA
    if _TAREA is not None and not _TAREA.done() and _TAREA.get_loop() is asyncio.get_running_loop():
        log.warning("La comprobación de microservicios ya está en marcha en este proceso; no se inicia otra")
        return _TAREA
    _TAREA = asyncio.create_task(
        _sin_excepciones(ejecutar(config, servicios, cliente, estado)), name="warmup-microservicios"
    )
    return _TAREA


async def detener(tarea: asyncio.Task | None) -> None:
    """Cancela el calentamiento si sigue corriendo (apagado del gateway) y espera a que termine."""
    if tarea is None:
        return
    if not tarea.done():
        tarea.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea
