# API Gateway

Punto de entrada único de LogiTrack. Reenvía las peticiones a Fleet Service y Shipment Service.

## Stack
FastAPI + httpx.

## Levantar en local
1. `python -m venv venv && venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` con las URLs de Fleet Service y Shipment Service corriendo localmente.
4. `uvicorn app.main:app --reload --port 8002`

## Endpoints (proxy)
- `GET /health`
- `GET /api/v1/vehiculos`, `GET /api/v1/vehiculos/{id}`, `POST /api/v1/vehiculos`
- `GET /api/v1/conductores`, `POST /api/v1/conductores`
- `POST /api/v1/envios`, `GET /api/v1/envios`, `GET /api/v1/envios/{id}`, `GET /api/v1/envios/{id}/eventos`, `PATCH /api/v1/envios/{id}/asignar`, `PATCH /api/v1/envios/{id}/estado`, `POST /api/v1/envios/{id}/prueba-entrega`

- `GET /api/v1/seguimiento/cliente/envio/{id}` (+ `/trazado`, `/recorrido`) — **solo rol cliente**: seguimiento de SU envío. Tracking valida el dueño con la identidad que inyecta el gateway. El resto de `/seguimiento`, `/telemetria` y `/simulaciones` es solo del personal (operador, gestor de flota, administrador) y los clientes lo reciben como 403.

> Nota: autenticación JWT todavía no está cableada en estas rutas — pendiente de diseño (ver decisión de arquitectura de auth).

## Calentamiento y health checks periódicos de los microservicios (Render)
En Render gratis cada servicio se duerme tras ~15 min sin tráfico entrante y tarda ~1–2 min en despertar. Al arrancar,
el gateway lanza una tarea en segundo plano (`app/calentamiento.py`) que hace `GET /health` a todos los servicios
configurados (`*_SERVICE_URL`) en paralelo, con reintentos y la clave interna (`X-Internal-Key`). No retrasa el
arranque: el gateway responde desde el primer momento. Después, **cada servicio tiene su propia tarea de
comprobación** que le repite `GET /health` cada `WARMUP_INTERVALO_MIN` minutos (**5 por defecto**; para 10 minutos
usa `WARMUP_INTERVALO_MIN=10`; `0` = solo al arrancar). Son independientes: un servicio caído no frena a los demás,
y sus reintentos están acotados (2 intentos por comprobación y 24 al arrancar). Las comprobaciones se reparten dentro
del intervalo (no salen las 9 a la vez). El `/health` de los microservicios es estático (no toca PostgreSQL ni
RabbitMQ) y la comprobación es siempre un `GET`: no ejecuta operaciones de negocio.

| Variable | Por defecto | Qué hace |
|---|---|---|
| `WARMUP_ACTIVO` | `true` | `false` desactiva todo (calentamiento y comprobaciones) |
| `WARMUP_INTERVALO_MIN` | `5` | Minutos entre comprobaciones por servicio (300 s). `10` = 600 s. `0` = solo al arrancar. Debe ser menor de 15 |
| `WARMUP_INTENTOS_PERIODICOS` | `2` | Intentos por comprobación (el 2.º cubre a un servicio que se está despertando) |
| `WARMUP_INTENTOS` | `0` | Intentos del calentamiento inicial. `0` = sin límite (con comprobación periódica se acota a 24) |
| `WARMUP_PAUSA_S` | `5` | Segundos entre intentos |
| `WARMUP_TIMEOUT_S` | `30` | Espera máxima de cada intento |
| `WARMUP_SERVICIOS` | vacío | Nombres separados por coma para vigilar solo algunos (`fleet,billing`) |

**Logs:** el calentamiento inicial se anuncia por servicio; después solo se escribe cuando un servicio deja de
responder o vuelve (`[WARNING] ... dejó de responder`, `[SUCCESS] ... volvió a responder`) y un resumen por servicio y
hora (`Health check periódico de fleet: 12 comprobación(es) y 0 fallo(s) en la última hora`). El estado también está en
`GET /health` (campo `calentamiento`) y, con sesión de administrador, en `GET /api/v1/estado`.

**Consumo:** 9 servicios × 12 comprobaciones/hora = 108 peticiones/hora (2.592 al día con 5 min; la mitad con 10 min).
Cada respuesta pesa unos 50 bytes de cuerpo más cabeceras: del orden de pocos MB al día.

### Límites que ningún código resuelve (léelos antes de activarlo en producción)
- **Comprobar la salud no garantiza que el servicio siga despierto.** Una petición entrante a un servicio gratis reinicia
  su cuenta de inactividad de 15 min (y despierta uno dormido), pero la plataforma puede reiniciar o suspender
  servicios gratis cuando quiera.
- **Las 750 horas de instancia gratuitas al mes son por workspace y se comparten.** Mantener los 10 servicios
  despiertos todo el día gasta 240 horas por día: las 750 horas se agotan en ~3 días y Render suspende los servicios
  gratis hasta el mes siguiente. Úsalo en ventanas de demostración y desactívalo después (`WARMUP_ACTIVO=false` o
  `WARMUP_INTERVALO_MIN=0`).
- **El propio gateway también se duerme.** Si nadie le envía tráfico durante 15 min se suspende y, con él, las
  comprobaciones: no se despierta solo. Para que siga activo necesita tráfico entrante desde fuera (el frontend en uso
  o un monitor externo); esa decisión no está implementada.
- Si el workspace se suspende (horas o ancho de banda agotados), ningún servicio corre y hay que recuperar el
  workspace en Render (esperar el cambio de mes o pasar a un plan de pago) antes de que el gateway pueda comprobar nada.
