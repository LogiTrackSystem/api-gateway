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

---

<!-- entrega-final -->

## Descripción

Punto de entrada único (`/api/v1`): verifica el JWT, aplica los permisos por rol, reenvía la petición al microservicio correcto, maneja CORS y publica la documentación OpenAPI unificada.

- **Puerto local:** 8002   ·   **Despliegue activo:** <https://logitrack-gateway.onrender.com> (`/health` y `/metrics` públicos)
- **Imagen Docker:** `<usuario-dockerhub>/logitrack-gateway`   ·   **Repositorio de CI/CD:** `LogiTrackSystem/pipelines`

## Variables de entorno

Copia `.env.example` como `.env` y completa los valores. El `.env` **no se sube** al repositorio.

| Variable | Para qué sirve |
|---|---|
| `JWT_SECRET` | Secreto para firmar y verificar los tokens (mínimo 16 caracteres; el mismo valor en Shipment y en el gateway). Es un secreto. |
| `FLEET_SERVICE_URL` | URL base de Fleet Service, sin barra final (en local `http://localhost:<puerto>`). |
| `SHIPMENT_SERVICE_URL` | URL base de Shipment Service, sin barra final (en local `http://localhost:<puerto>`). |
| `ROUTING_SERVICE_URL` | URL base de Routing Service, sin barra final (en local `http://localhost:<puerto>`). |
| `TRACKING_SERVICE_URL` | URL base de Tracking Service, sin barra final (en local `http://localhost:<puerto>`). |
| `MAINTENANCE_SERVICE_URL` | URL base de Maintenance Service, sin barra final (en local `http://localhost:<puerto>`). |
| `CUSTOMS_SERVICE_URL` | URL base de Customs Service, sin barra final (en local `http://localhost:<puerto>`). |
| `NOTIFICATION_SERVICE_URL` | URL base de Notification Service, sin barra final (en local `http://localhost:<puerto>`). |
| `BILLING_SERVICE_URL` | URL base de Billing Service, sin barra final (en local `http://localhost:<puerto>`). |
| `ANALYTICS_SERVICE_URL` | URL base de Analytics Service, sin barra final (en local `http://localhost:<puerto>`). |
| `CORS_ORIGINS` | Orígenes permitidos del navegador (URL del frontend), separados por coma. |
| `GATEWAY_TIMEOUT_S` | Tiempo máximo de espera (s) por la respuesta de un servicio (por defecto 65). |
| `INTERNAL_API_KEY` | Clave compartida entre el gateway y los servicios: exige la cabecera `X-Internal-Key` en todas las rutas salvo `/health` y `/metrics`. Vacía = sin restricción (solo local). Es un secreto. |

## Documentación de la API

Swagger unificado de todo el sistema: <https://logitrack-gateway.onrender.com/docs> (local: <http://localhost:8002/docs>). El contrato completo está en `docs/CONTRATO_API.md`.

## Base de datos

Este servicio no usa base de datos propia.

## Pruebas

Con el entorno virtual activo y `pip install -r requirements-dev.txt`:

```
pytest tests/unit                    # 2 pruebas unitarias
pytest tests/integration             # 1 prueba de integración
pytest --cov=app --cov-report=term   # toda la suite con cobertura
```

| Prueba | Qué verifica |
|---|---|
| Unitaria 1 | `jwt_simple.verificar_token` |
| Unitaria 2 | `permisos.autorizar` |
| Integración | petición HTTP sin token (401) y con token (reenvío con la identidad al servicio) |

Archivos: `tests/unit/` y `tests/integration/` (test_verificar_token.py, test_autorizar.py, test_flujo_gateway.py). Cobertura de `app/` medida: **≈ 88 %**; en cada push y Pull Request GitHub Actions la recalcula y guarda `coverage.xml` como artefacto (`cobertura-gateway`).

## Métricas y monitoreo

Expone `GET /metrics` (formato Prometheus: `http_requests_total` y `http_request_duration_*`). Prometheus y el dashboard de Grafana están en el repositorio `logitrack-monitoring`.

## CI/CD

- `.github/workflows/pr.yml`: en cada push (rama distinta de `main`) y en cada Pull Request a `main` ejecuta el CI reutilizable (lint, pruebas con cobertura, `docker build` y prueba de arranque).
- `.github/workflows/deploy.yml`: al fusionar en `main`, y solo con las pruebas en verde, publica la imagen en Docker Hub y despliega en Render (con verificación de `/health` y rollback manual).
- Detalle y estrategia de ramas: `CICD.md` en el repositorio `LogiTrackSystem/pipelines`.

