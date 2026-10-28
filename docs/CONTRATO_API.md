# LogiTrack — Contrato de la API para el frontend

Documento de referencia para quien construye la interfaz web de LogiTrack. Describe **todas las rutas públicas** del API Gateway, qué enviar, qué responde, qué errores pueden aparecer y cómo conviene consumirlas.

> **Fuente de verdad.** Las tablas de campos de la sección 6 se generaron a partir del `openapi.json` real del gateway (`GET http://localhost:8002/openapi.json`, también navegable en `http://localhost:8002/docs`). Si el backend cambia, la documentación viva es esa. Este documento agrega lo que el OpenAPI no dice: descripciones, errores, estados, flujos y recomendaciones de consumo.

**Contenido**

1. Convenciones generales
2. Errores
3. Estados
4. Qué pasa cuando se crea un envío (flujo automático)
5. Cómo consumir la API desde el frontend
6. Referencia de endpoints (83 rutas)
7. Modelos de respuesta
8. Limitaciones conocidas y decisiones de diseño

---

## 1. Convenciones generales

### 1.1 Dirección base y servicios

El frontend habla **solo con el API Gateway**; nunca con los microservicios directamente.

| Entorno | URL base |
|---|---|
| Desarrollo local | `http://localhost:8002/api/v1` |

Cada ruta de este documento se escribe sin la base: `GET /envios` significa `GET http://localhost:8002/api/v1/envios`.

La única ruta fuera de ese prefijo es `GET http://localhost:8002/health` (salud del propio gateway).

Las rutas de colecciones funcionan **con o sin barra final** (`/envios` y `/envios/`). El gateway las normaliza.

### 1.2 Formato

- Cuerpo y respuestas en JSON (`Content-Type: application/json`), codificación UTF-8.
- Nombres de campo en `snake_case` y en español.
- **Fechas y horas:** ISO 8601 (`2026-10-11T15:30:00Z`). Trátelas como UTC y conviértalas a la hora local (`America/Bogota`, UTC−5) solo al mostrarlas.
- **Identificadores.** Cada recurso tiene un `id` (UUID, para usar en las rutas) y, cuando aplica, un código legible para mostrar al usuario: `codigo_envio` (`ENV-00000032`), `codigo_ruta` (`RUT-00000013`), `codigo_cliente` y `codigo_conductor` (numéricos, desde `1000000001`), y la `placa` del vehículo. Muchas rutas de consulta tienen una variante `/codigo/{codigo}`.
- **Decimales.** Varios servicios (Fleet, Shipment, Routing, Billing) devuelven los decimales como **texto** (`"peso_kg": "800.00"`), mientras que Tracking devuelve números (`"progreso_pct": 41.2`). Convierta con `Number(...)` antes de operar. Al enviar, en general se aceptan ambos formatos.
- **Listas.** Las respuestas de colección son un arreglo JSON simple (sin envoltorio de paginación). Donde hay filtro `limite`, ese es el único control de tamaño.

### 1.3 Autenticación

**Hoy la API no exige autenticación.** Cualquier cliente que llegue al gateway puede llamar a cualquier ruta. El gateway ya reenvía la cabecera `Authorization` a los servicios, de modo que cuando se incorpore JWT bastará con enviarla; el frontend no necesita cambiar su forma de llamar, solo agregar la cabecera. En cada endpoint de la sección 6 la autenticación figura como «ninguna» por esta razón.

### 1.4 CORS y cabeceras

- El gateway acepta peticiones desde los orígenes definidos en su variable `CORS_ORIGINS` (por defecto `http://localhost:5173`, `http://localhost:3000` y `http://localhost:4200`). **Si el frontend corre en otro origen, hay que añadirlo ahí y reiniciar el gateway.**
- Cada respuesta incluye `X-Request-ID` (identificador de la petición; puede enviarlo usted mismo y se conserva) y `X-Gateway-Servicio` (qué microservicio la atendió). Son visibles desde JavaScript. Útiles para reportar un error: «el `X-Request-ID` fue `a1b2c3`».
- No se usan cookies: haga las peticiones sin credenciales (`credentials: 'omit'`, que es el valor por defecto de `fetch` entre orígenes distintos).

### 1.5 Tiempos de espera

El gateway espera hasta **65 s** a un microservicio. Crear un envío puede tardar algunos segundos la primera vez que se pide una ruta entre dos ciudades nuevas (se consulta un servicio de mapas). Muestre un indicador de carga en `POST /envios`.

### 1.6 Probar sin frontend

- `http://localhost:8002/docs` — Swagger con todas las rutas de este documento (se construye uniendo los OpenAPI de los servicios; si un servicio está apagado, sus rutas no aparecen).
- `GET /estado` — salud de los 9 servicios.
- El script `_pruebas/casos.py` recorre de punta a punta los casos de uso del proyecto usando solo estas rutas; sirve como ejemplo ejecutable.

---

## 2. Errores

### 2.1 Formas del campo `detail`

Toda respuesta de error tiene la forma `{"detail": …}`, y `detail` puede venir en **tres formatos**. El frontend debe tratar los tres:

| Forma | Cuándo | Ejemplo |
|---|---|---|
| Objeto con código | Errores de negocio que el frontend puede distinguir | `{"detail": {"codigo": "CAPACIDAD_EXCEDIDA", "mensaje": "Ningún vehículo con conductor puede transportar 9000 kg (la mayor capacidad de la flota es 5000 kg)"}}` |
| Texto | Errores simples (no encontrado, duplicado…) | `{"detail": "Envío no encontrado"}` |
| Lista | Validación de campos (422 automático de FastAPI) | `{"detail": [{"loc": ["body", "peso_kg"], "msg": "Input should be greater than 0", "type": "greater_than"}]}` |

Algunos 422 de negocio traen un objeto sin `codigo`, por ejemplo la elegibilidad de un conductor: `{"detail": {"mensaje": "…", "errores": ["…", "…"]}}`.

Función sugerida para mostrar cualquier error:

```js
function mensajeDeError(cuerpo, estado) {
  const d = cuerpo?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(e => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('\n');
  if (d && typeof d === 'object') {
    if (d.errores?.length) return `${d.mensaje}: ${d.errores.join('; ')}`;
    return d.mensaje || d.codigo || `Error ${estado}`;
  }
  return `Error ${estado}`;
}
```

Para decidir la lógica (no solo mostrar texto), use `detail.codigo` cuando exista: es estable. El texto de los mensajes puede cambiar.

### 2.2 Códigos HTTP

| HTTP | Significado |
|---|---|
| 200 / 201 | Éxito (201 al crear un recurso). |
| 404 | El recurso no existe. |
| 409 | Conflicto con el estado actual (duplicado, transición no permitida, vehículo ocupado…). |
| 422 | Datos inválidos: formato incorrecto o regla de negocio (cliente inexistente, carga imposible…). |
| 502 / 503 / 504 | Problema entre el gateway y un microservicio (sección 2.3). |

### 2.3 Errores propios del gateway

Siempre con formato objeto y con el campo extra `servicio` cuando aplica. Son los mismos para cualquier ruta.

| HTTP | `codigo` | Significado | Qué hacer en el frontend |
|---|---|---|---|
| 404 | `RUTA_NO_ENCONTRADA` | La ruta no existe en `/api/v1`. | Es un error de programación. |
| 405 | `METODO_NO_PERMITIDO` | La ruta existe pero no admite ese método. | Error de programación. |
| 503 | `SERVICIO_NO_DISPONIBLE` | El microservicio está caído o no responde. | Mensaje «servicio no disponible, reintente»; reintentar con espera. |
| 503 | `SERVICIO_NO_CONFIGURADO` | El gateway no tiene la URL del servicio. | Avisar al administrador. |
| 504 | `SERVICIO_LENTO` | El servicio tardó más de 65 s. | Reintentar; no repetir si fue un `POST` sin antes consultar si se creó. |
| 502 | `ERROR_DE_GATEWAY` | Falla de comunicación inesperada. | Reintentar. |

Cuando el microservicio responde (aunque sea con error), el gateway devuelve **su** código HTTP y **su** cuerpo sin cambios.

---

## 3. Estados

### 3.1 Estados del envío (`estado`)

| Estado | Significado |
|---|---|
| `pendiente` | Recién creado; el sistema está buscando vehículo (dura segundos). |
| `sin_asignacion` | No había vehículo+conductor libre compatible. El sistema reintenta solo (cada 30 s, luego 1 min, 2 min… hasta 10 min) y se asigna apenas se libere uno. `motivo_sin_asignacion` explica por qué. |
| `asignado` | Tiene vehículo, conductor y hora estimada de llegada; el viaje está por empezar. |
| `en_transito` | El vehículo está en camino. |
| `con_incidencia` | Marcado manualmente con una incidencia. |
| `retenido_aduana` | Envío internacional retenido por Aduanas; el viaje queda en pausa. |
| `entregado` | Terminado (final). Tiene prueba de entrega. |
| `devuelto` | Cancelado/devuelto (final). Libera el vehículo. |

**Transiciones automáticas** (el frontend no las provoca):

```
pendiente ──► asignado ──► en_transito ──► entregado
    │            ▲
    └─► sin_asignacion ─┘      (se asigna solo cuando hay vehículo)

cualquier estado no final ◄──► retenido_aduana   (Aduanas retiene / libera; al liberar vuelve al estado previo)
```

**Transiciones manuales** (`PATCH /envios/{id}/estado`, solo casos excepcionales):

| Estado destino | Se permite desde |
|---|---|
| `en_transito` | `asignado`, `con_incidencia` |
| `con_incidencia` | `asignado`, `en_transito` |
| `devuelto` | `pendiente`, `sin_asignacion`, `asignado`, `en_transito`, `con_incidencia`, `retenido_aduana` |

`entregado` se logra solo, o con `POST /envios/{id}/prueba-entrega` desde `asignado`, `en_transito` o `con_incidencia`. Los estados finales (`entregado`, `devuelto`) no admiten más cambios. Una transición no permitida responde **409 `TRANSICION_INVALIDA`**.

### 3.2 Estado de la ruta de un envío (`/rutas`)

`sin_asignacion` → `asignada` → `en_curso` → `finalizada`; además `por_liberar` (esperando liberar la reserva), `cancelada`, `historica` (reemplazada por una ruta nueva) y `manual`. Para una pantalla de operador basta mostrar el estado del **envío**; la ruta es detalle técnico.

### 3.3 Estado del viaje (`estado_viaje` en `/seguimiento`)

| Valor | Significado |
|---|---|
| `preparando` | Se está armando el viaje (segundos). |
| `en_curso` | El vehículo avanza. |
| `pausada` | Detenido por Aduanas. |
| `finalizada` | Llegó al destino. |
| `cancelada` | El envío fue devuelto. |

### 3.4 Estados de vehículo y conductor

- **Vehículo** (`estado`): `active` (libre), `en_transito` (en una reserva/viaje), `en_mantenimiento`, `fuera_de_servicio`. El sistema pone y quita `en_transito` solo.
- **Conductor** (`estado`): `available` (libre) o `en_ruta`. También lo gestiona el sistema.
- Un vehículo con motor sobre 110 °C pasa solo a `en_mantenimiento` (Mantenimiento lo detecta por telemetría).

---

## 4. Qué pasa cuando se crea un envío (flujo automático)

El frontend solo hace `POST /envios`. Todo lo demás ocurre en el backend y se observa consultando el envío:

| # | Qué ocurre | Cómo se ve en la API | Tiempo típico |
|---|---|---|---|
| 1 | Se valida el cliente (debe existir y estar activo) y se resuelve origen/destino del catálogo. | Errores 422 inmediatos. | instantáneo |
| 2 | Se obtiene la ruta por carretera (o se reutiliza la ya calculada) y se deduce si es internacional. | La respuesta trae `codigo_ruta`, `distancia_km`, `duracion_horas`. | 1 s (hasta unos segundos si la ruta es nueva) |
| 3 | **Viabilidad:** si ninguna pareja vehículo+conductor de la flota podría llevar la carga, se rechaza. | **422** con `codigo` = `CAPACIDAD_EXCEDIDA`, `VOLUMEN_EXCEDIDO`, `SIN_REFRIGERACION`, `SIN_HABILITACION_HAZMAT` o `SIN_FLOTA_OPERATIVA`. | instantáneo |
| 4 | Se guarda el envío en `pendiente` y responde **201**. | `estado: "pendiente"`. | — |
| 5 | Routing reserva vehículo+conductor de forma atómica (mejor ajuste: el vehículo suficiente más pequeño, y solo conductores habilitados). | El envío pasa a `asignado` con `placa_vehiculo`, `conductor_nombre`, `hora_estimada_llegada`. Si no hay nadie libre: `sin_asignacion` + `motivo_sin_asignacion`. | 1–3 s |
| 6 | Tracking arranca el viaje automáticamente. | `estado: "en_transito"`; `/seguimiento/envio/{id}` deja de dar 404. Si es internacional y Aduanas lo retiene: `retenido_aduana`. | 1–10 s |
| 7 | El vehículo avanza cada 5 s: posición, velocidad, combustible, paradas y recargas. | `/seguimiento/…` cambia en cada consulta. | duración real de la ruta ÷ factor de tiempo (sección 5.4) |
| 8 | Al llegar, el envío pasa a `entregado` y se registra una **prueba de entrega simulada** (`simulada: true`, receptor «Entrega simulada automática»). El vehículo y el conductor quedan libres. | `GET /envios/{id}/prueba-entrega`. | segundos tras la llegada |
| 9 | Si había envíos esperando vehículo, el primero recibe el que se liberó. | Un envío pasa de `sin_asignacion` a `asignado`. | segundos |

Además, cada paso deja una línea en la bitácora `GET /envios/{id}/eventos` (para una línea de tiempo en el detalle del envío) y genera notificaciones (`GET /notificaciones`).

**Si el viaje está pausado por Aduanas** (solo envíos internacionales), el envío queda `retenido_aduana` y el seguimiento muestra `estado_viaje: "pausada"` hasta que Aduanas lo libere (`PATCH /declaraciones/{id}/estado` con `aprobado`).

---

## 5. Cómo consumir la API desde el frontend

### 5.1 Crear un envío (formulario)

1. **Cliente:** buscador con `GET /clientes?q=texto`; si no existe, `POST /clientes`. En el envío se puede indicar `cliente_id` (uuid) **o** `codigo_cliente`.
2. **Origen y destino:** buscador con `GET /ubicaciones?q=texto` (y `GET /ubicaciones/paises` para un filtro por país). En el envío se envía `origen_id`/`destino_id` o `origen_codigo`/`destino_codigo` (por ejemplo `CO-MTR`).
3. **Carga:** `peso_kg` (obligatorio), `volumen_m3`, `tipo_carga` (`general` o `refrigerada`), `es_hazmat`. No envíe `es_internacional`: se deduce de los países.
4. **Aviso previo (opcional):** al cambiar peso, tipo o HAZMAT, `POST /viabilidad` devuelve `viable: false` con un `mensaje` listo para mostrar, antes de que el usuario envíe el formulario.
5. `POST /envios` → 201. Mostrar la ficha del envío y consultar `GET /envios/{id}` cada 2 s hasta que `estado` deje de ser `pendiente` (suelen ser 1–3 s; abandone a los 30 s y muestre «asignación en proceso»).

Errores esperables al enviar: 422 con `codigo` de viabilidad (mostrar `mensaje`), 422 de texto («El cliente no existe…», «es_internacional contradice las ubicaciones…»), 503 `ROUTING_NO_DISPONIBLE` (reintentar).

### 5.2 Lista y detalle de envíos

- Tabla: `GET /envios?estado=…&cliente_id=…`. Refresque cada 10 s o con un botón.
- Detalle: `GET /envios/{id}` o `GET /envios/codigo/{codigo_envio}`; línea de tiempo con `GET /envios/{id}/eventos`.
- Si `estado` es `sin_asignacion` mostrar `motivo_sin_asignacion` y un botón «Reintentar ahora» (`POST /envios/{id}/reintentar-asignacion`). El sistema ya reintenta solo; el botón es una comodidad.
- Cuando el envío esté `entregado`, mostrar `GET /envios/{id}/prueba-entrega` (si `simulada` es `true`, rotularla como «entrega simulada»).

### 5.3 Mapa de seguimiento (el endpoint más importante)

Flujo recomendado para la pantalla de un envío en tránsito:

1. **Una vez**, al abrir la pantalla: `GET /seguimiento/envio/{id}/trazado` → polilínea completa de la ruta y paradas. Dibújela con la librería de mapas (Leaflet, Google Maps…). No cambia durante el viaje.
2. **Cada 3–5 s**: `GET /seguimiento/envio/{id}` → posición del camión, porcentaje de progreso, hora estimada de llegada, combustible, parada actual y estado de cada parada. Mueva el marcador con `posicion.latitud`/`posicion.longitud`.
3. **Opcional:** `GET /seguimiento/envio/{id}/recorrido` para pintar la estela ya recorrida (por ejemplo al recargar la página).
4. Detenga el polling cuando `estado_viaje` sea `finalizada` o `cancelada`.

```js
async function vigilarViaje(envioId, pintar, cada = 4000) {
  let activo = true;
  async function tick() {
    if (!activo) return;
    const r = await fetch(`${BASE}/seguimiento/envio/${envioId}`);
    if (r.ok) {
      const s = await r.json();
      pintar(s);
      if (['finalizada', 'cancelada'].includes(s.estado_viaje)) return;
    } else if (r.status !== 404 && r.status !== 409) {
      // 404 SIN_VIAJE (todavía sin viaje) y 409 VIAJE_EN_PREPARACION son normales: seguir intentando
      console.warn(await r.json());
    }
    setTimeout(tick, cada);
  }
  tick();
  return () => { activo = false; };
}
```

- **`404 SIN_VIAJE`** no es un fallo: el envío aún no tiene viaje porque está `pendiente`/`sin_asignacion`. Muestre «esperando vehículo».
- **Mapa general de la flota:** `GET /seguimiento/flota` (una fila por vehículo en viaje, con posición, progreso y combustible) cada 5 s.
- **Ficha por vehículo:** `GET /seguimiento/vehiculo/{vehiculo_id}`; da 404 `SIN_VIAJE_ACTIVO` si no está en ruta.
- Para el consumo de combustible y el odómetro del vehículo, `GET /telemetria/{vehiculo_id}?limite=50`.

### 5.4 El factor de tiempo simulado

El movimiento de los vehículos es una **simulación acelerada**. Tracking recorre la ruta `SIM_FACTOR_TIEMPO` veces más rápido que la realidad (por defecto 120): un viaje de 6 horas dura unos 3 minutos. La respuesta de seguimiento incluye `factor_tiempo` para que la interfaz lo sepa.

Qué significa para la pantalla:

- `tiempos.hora_estimada_llegada` y `tiempos.segundos_restantes` están en **tiempo de pared** (la hora real en que llegará en la simulación), así que se pueden mostrar tal cual.
- `posicion.velocidad_kmh` es la velocidad **virtual** (la de un camión real, ~60–70 km/h), no la velocidad a la que se mueve el marcador. No la use para calcular cuánto debería avanzar el marcador entre dos consultas: tome siempre la posición recibida.
- Si el equipo quiere mostrar «tiempo de viaje real», multiplique por `factor_tiempo`.

### 5.5 Catálogos y pantallas de administración

| Pantalla | Rutas |
|---|---|
| Flota | `GET/POST /vehiculos`, `PATCH /vehiculos/{id}`, `GET /vehiculos/placa/{placa}` |
| Conductores | `GET/POST /conductores`, `PATCH /conductores/{id}`, `PUT /conductores/{id}/vehiculo` (liga a un vehículo; permanente), `GET /conductores/auditoria-vinculos` |
| Clientes | `GET/POST /clientes`, `PATCH /clientes/{id}` |
| Ubicaciones | `GET/POST /ubicaciones`, `PATCH /ubicaciones/{id}` |
| Aduanas | `GET /declaraciones?estado=…`, `PATCH /declaraciones/{id}/estado` |
| Mantenimiento | `POST /programas`, `GET /programas/{vehiculo_id}`, `POST /intervenciones`, `GET /intervenciones/{vehiculo_id}` |
| Facturación | `GET/POST /tarifas`, `GET /costos-ruta`, `GET /facturas`, `POST /facturas/cerrar-periodo` |
| Dashboard | `GET /dashboard/*` (7 indicadores); `POST /etl/ejecutar` fuerza la actualización |
| Notificaciones | `GET /notificaciones`, `POST/GET /preferencias/{cliente_id}` |
| Estado del sistema | `GET /estado` |

**Reglas que el formulario de conductor/vehículo debe conocer:**

- Un conductor se liga **de forma permanente** a un vehículo (un conductor, un vehículo). Un vehículo sin conductor nunca se asigna a envíos.
- Elegibilidad al ligar: furgoneta exige licencia B1/C1 o superior y 1 año de experiencia; camión, B2/C2 o superior y 2 años; tractocamión, B3/C3 y 3 años. Para un vehículo con `certificado_hazmat` el conductor debe tener `certificacion_hazmat` y al menos 3 años. Si no cumple: 422 con la lista de motivos en `detail.errores`.
- Un envío `refrigerada` solo se asigna a vehículos con `capacidad_refrigeracion`; uno `es_hazmat`, solo a vehículos con `certificado_hazmat` y conductores habilitados.

### 5.6 Qué NO hay que hacer desde el frontend

- No asignar vehículos a mano ni cambiar el estado de un envío a `asignado`: es automático (esa ruta fue eliminada).
- No llamar a Fleet ni a Routing directamente ni inventar rutas fuera de `/api/v1`: lo que no está en este documento no es público.
- No guardar la posición del camión como dato propio: se consulta.

### 5.7 Índice rápido de endpoints

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/v1/estado` | Salud de los 9 microservicios (útil para un indicador en el panel). |
| GET | `/health` | Comprueba que el gateway está vivo (esta ruta está fuera de `/api/v1`: `GET http://localhost:8002/health`). |
| GET | `/api/v1/clientes` | Lista clientes. |
| POST | `/api/v1/clientes` | Registra un cliente. |
| GET | `/api/v1/clientes/{cliente_id}` | Detalle de un cliente por su `id`. |
| PATCH | `/api/v1/clientes/{cliente_id}` | Modifica un cliente (solo los campos enviados). |
| GET | `/api/v1/clientes/codigo/{codigo}` | Busca un cliente por su `codigo_cliente`. |
| GET | `/api/v1/ubicaciones` | Lista ubicaciones. |
| POST | `/api/v1/ubicaciones` | Agrega una ubicación al catálogo. |
| GET | `/api/v1/ubicaciones/paises` | Países que tienen ubicaciones activas, con su total. |
| GET | `/api/v1/ubicaciones/{ubicacion_id}` | Detalle de una ubicación por su `id`. |
| PATCH | `/api/v1/ubicaciones/{ubicacion_id}` | Modifica una ubicación (por ejemplo para desactivarla). |
| GET | `/api/v1/ubicaciones/codigo/{codigo}` | Busca una ubicación por su código (por ejemplo `CO-MTR`). |
| GET | `/api/v1/vehiculos` | Lista todos los vehículos. |
| POST | `/api/v1/vehiculos` | Registra un vehículo. |
| GET | `/api/v1/vehiculos/{vehicle_id}` | Detalle de un vehículo por su `id`. |
| PATCH | `/api/v1/vehiculos/{vehicle_id}` | Modifica datos del vehículo (solo los campos enviados). |
| GET | `/api/v1/vehiculos/placa/{placa}` | Busca un vehículo por placa. |
| PATCH | `/api/v1/vehiculos/{vehicle_id}/estado` | Cambia el estado del vehículo. |
| GET | `/api/v1/conductores` | Lista todos los conductores. |
| POST | `/api/v1/conductores` | Registra un conductor. |
| GET | `/api/v1/conductores/auditoria-vinculos` | Revisa cada vínculo conductor↔vehículo contra las reglas actuales de elegibilidad. |
| GET | `/api/v1/conductores/{conductor_id}` | Detalle de un conductor por su `id`. |
| PATCH | `/api/v1/conductores/{conductor_id}` | Modifica datos del conductor (solo los campos enviados). |
| GET | `/api/v1/conductores/codigo/{codigo}` | Busca un conductor por su `codigo_conductor`. |
| PUT | `/api/v1/conductores/{conductor_id}/vehiculo` | Liga el conductor a un vehículo de forma permanente (un conductor, un vehículo). |
| POST | `/api/v1/viabilidad` | Pregunta si alguna pareja vehículo+conductor de la flota podría transportar esa carga. |
| GET | `/api/v1/reservas/envio/{envio_id}` | Reserva de flota más reciente de un envío: qué vehículo y conductor se le reservaron y si sigue vigente (`reservada`) o ya se liberó (`liberada`). |
| GET | `/api/v1/envios` | Lista envíos. |
| POST | `/api/v1/envios` | Crea un envío y dispara todo el flujo automático. Origen y destino se envían por id o por código (uno de los dos). |
| GET | `/api/v1/envios/{envio_id}` | Detalle de un envío, con la asignación (vehículo, conductor, ruta, hora estimada) cuando ya existe. |
| GET | `/api/v1/envios/codigo/{codigo_envio}` | Busca un envío por su código (`ENV-00000032`). |
| PATCH | `/api/v1/envios/{envio_id}/estado` | Cambio manual de estado, solo para casos excepcionales: el único estado destino aceptado es `en_transito`, `con_incidencia` o `devuelto` (opcional `notas`). |
| GET | `/api/v1/envios/{envio_id}/eventos` | Bitácora del envío (línea de tiempo): creado, asignado, en tránsito, retenido, entregado, etc., en orden. |
| GET | `/api/v1/envios/{envio_id}/prueba-entrega` | Prueba de entrega del envío. |
| POST | `/api/v1/envios/{envio_id}/prueba-entrega` | Registra una prueba de entrega manual y deja el envío `entregado`. |
| POST | `/api/v1/envios/{envio_id}/reintentar-asignacion` | Pide reintentar ya la asignación de un envío que espera vehículo (`pendiente` o `sin_asignacion`). |
| GET | `/api/v1/rutas-maestras` | Lista rutas maestras. |
| POST | `/api/v1/rutas-maestras/calcular` | Calcula (o devuelve si ya existe) la ruta por carretera entre dos ubicaciones. |
| GET | `/api/v1/rutas-maestras/{ruta_id}` | Detalle de una ruta maestra, con sus paradas (ciudades a 20 km o menos de la vía). |
| GET | `/api/v1/rutas-maestras/codigo/{codigo_ruta}` | Busca una ruta maestra por su código (`RUT-00000013`). |
| GET | `/api/v1/rutas-maestras/{ruta_id}/geometria` | Trazado para dibujar la ruta en el mapa. |
| POST | `/api/v1/rutas-maestras/{ruta_id}/recalcular` | Vuelve a consultar el servicio de mapas y reemplaza los datos (por ejemplo para mejorar una ruta estimada). |
| GET | `/api/v1/rutas` | Lista rutas de envío. |
| GET | `/api/v1/rutas/{ruta_id}` | Detalle de una ruta de envío. |
| GET | `/api/v1/rutas/{ruta_id}/historial` | Historial de cambios de la ruta. |
| PATCH | `/api/v1/rutas/{ruta_id}/recalcular` | Recalcula la ruta manualmente (uso excepcional del operador). |
| POST | `/api/v1/asignaciones/reintentar` | Fuerza ahora un barrido general: reasigna lo que está sin asignación y publica eventos pendientes. |
| POST | `/api/v1/asignaciones/envio/{envio_id}/reintentar` | Reintenta la asignación de un envío concreto y devuelve su ruta. |
| GET | `/api/v1/seguimiento/flota` | Resumen de todos los viajes en curso (una fila por vehículo), pensado para el mapa general. |
| GET | `/api/v1/seguimiento/codigo/{codigo_envio}` | Igual que `/seguimiento/envio/{id}` pero buscando por código de envío. |
| GET | `/api/v1/seguimiento/envio/{envio_id}` | Ficha completa del viaje de un envío: posición, progreso, tiempos y hora estimada, combustible, parada actual y paradas. |
| GET | `/api/v1/seguimiento/vehiculo/{vehiculo_id}` | Seguimiento del viaje que está haciendo ahora un vehículo. |
| GET | `/api/v1/seguimiento/envio/{envio_id}/recorrido` | Puntos ya recorridos por el vehículo (para pintar la estela). |
| GET | `/api/v1/seguimiento/envio/{envio_id}/trazado` | Trazado completo de la ruta (puntos y paradas) para dibujarlo una sola vez; no cambia durante el viaje. |
| GET | `/api/v1/simulaciones` | Lista simulaciones de viaje. |
| GET | `/api/v1/simulaciones/envio/{envio_id}` | Estado interno de la simulación del viaje de un envío. |
| GET | `/api/v1/simulaciones/envio/{envio_id}/eventos` | Bitácora del viaje: inicio, paradas, recargas, pausas por aduana y llegada. |
| GET | `/api/v1/telemetria/{vehiculo_id}` | Lecturas de telemetría de un vehículo, de la más nueva a la más antigua. |
| POST | `/api/v1/programas` | Crea un programa de mantenimiento preventivo para un vehículo. |
| GET | `/api/v1/programas/{vehiculo_id}` | Programas de mantenimiento de un vehículo. |
| POST | `/api/v1/intervenciones` | Registra una intervención de mantenimiento realizada. |
| GET | `/api/v1/intervenciones/{vehiculo_id}` | Intervenciones de mantenimiento de un vehículo. |
| GET | `/api/v1/declaraciones` | Lista declaraciones aduaneras. |
| GET | `/api/v1/declaraciones/{envio_id}` | Declaración aduanera de un envío internacional. |
| PATCH | `/api/v1/declaraciones/{declaracion_id}/estado` | Cambia el estado de la declaración (`pendiente`, `retenido`, `aprobado`; opcional `motivo_retencion`). |
| GET | `/api/v1/notificaciones` | Notificaciones generadas, de la más reciente a la más antigua. |
| GET | `/api/v1/preferencias/{cliente_id}` | Preferencia del cliente. |
| POST | `/api/v1/preferencias/{cliente_id}` | Guarda la preferencia de un cliente: `idioma` (`es` o `en`) y `canal_preferido` (`sms`, `email` o `push`, opcional). |
| POST | `/api/v1/tarifas` | Define el modelo de cobro de un cliente. |
| GET | `/api/v1/tarifas/{cliente_id}` | Tarifa de un cliente. |
| GET | `/api/v1/costos-ruta` | Costos calculados por envío. |
| GET | `/api/v1/facturas` | Lista facturas. |
| POST | `/api/v1/facturas/cerrar-periodo` | Cierra el periodo actual y genera las facturas pendientes. |
| GET | `/api/v1/facturas/{factura_id}` | Detalle de una factura. |
| GET | `/api/v1/dashboard/actividad-reciente` | Últimos eventos del sistema. |
| GET | `/api/v1/dashboard/costo-por-km` | Costo por kilómetro por tipo de vehículo. |
| GET | `/api/v1/dashboard/eficiencia-combustible` | Eficiencia de combustible por conductor. |
| GET | `/api/v1/dashboard/entregas-diarias` | Entregas por día. |
| GET | `/api/v1/dashboard/proyeccion-mantenimiento` | Mantenimientos próximos. |
| GET | `/api/v1/dashboard/resumen` | Indicadores generales (envíos, entregas, flota, costos). |
| GET | `/api/v1/dashboard/utilizacion-flota` | Utilización de la flota. |
| POST | `/api/v1/etl/ejecutar` | Fuerza ahora el ciclo ETL que alimenta el dashboard y devuelve su resultado. |


---

## 6. Referencia de endpoints

Todas las rutas cuelgan de `/api/v1`. Los ejemplos de petición y respuesta son ilustrativos (valores inventados con la forma exacta que define el esquema); los campos `uuid` son identificadores internos y los `codigo_*` son los que se muestran al usuario.

### 6.1 Gateway (salud y estado)

Rutas propias del gateway. No cuelgan de ningún microservicio.


#### `GET /health`

Comprueba que el gateway está vivo (esta ruta está fuera de `/api/v1`: `GET http://localhost:8002/health`).

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `status` | string | `ok` |
| `service` | string | `api-gateway` |

Ejemplo:

```json
{
  "status": "ok",
  "service": "api-gateway"
}
```

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/estado`

Salud de los 9 microservicios (útil para un indicador en el panel). `estado_general` es `ok` o `degradado`; cada servicio trae `estado` (`ok`, `con_error`, `sin_respuesta`, `sin_configurar`) y `ms`.

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `estado_general` | string | `ok` si los 9 servicios responden; `degradado` si alguno no |
| `servicios` | objeto | Un campo por servicio: `fleet`, `shipment`, `routing`, `tracking`, `maintenance`, `customs`, `notification`, `billing`, `analytics` |
| `servicios.<nombre>.estado` | string | `ok`, `con_error`, `sin_respuesta` o `sin_configurar` |
| `servicios.<nombre>.ms` | integer | Milisegundos que tardó en responder (solo si respondió) |

Ejemplo:

```json
{
  "estado_general": "ok",
  "servicios": {
    "fleet": {
      "estado": "ok",
      "ms": 12
    },
    "shipment": {
      "estado": "ok",
      "ms": 9
    },
    "routing": {
      "estado": "ok",
      "ms": 11
    },
    "tracking": {
      "estado": "ok",
      "ms": 10
    },
    "maintenance": {
      "estado": "sin_respuesta"
    }
  }
}
```

**Errores**: solo los generales del gateway (sección 2).


### 6.2 Clientes

Los clientes los gestiona el operador. Un envío solo puede crearse para un cliente existente y activo.


#### `GET /api/v1/clientes`

Lista clientes. Filtros: `q` (busca por nombre, documento o código), `activo`, `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `q` | texto | no | puede ser `null` |
| `activo` | booleano | no | puede ser `null` |
| `limite` | entero | no | ≥ 1; ≤ 200; por defecto `50` |

**Respuesta 200** — lista de `ClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/clientes`

Registra un cliente. `codigo_cliente` lo asigna el sistema (desde 1000000001).

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre` | texto | sí | máx. 150 caracteres; mín. 2 caracteres |
| `tipo_documento` | enum | sí | valores: `CC`, `CE`, `NIT`, `PAS` |
| `numero_documento` | texto | sí | máx. 30 caracteres; mín. 3 caracteres |
| `email` | texto | no | máx. 150 caracteres; puede ser `null` |
| `telefono` | texto | no | máx. 30 caracteres; puede ser `null` |
| `direccion` | texto | no | máx. 255 caracteres; puede ser `null` |

Ejemplo:

```json
{
  "nombre": "Distribuidora del Caribe S.A.S.",
  "tipo_documento": "NIT",
  "numero_documento": "900123456-7",
  "email": "contacto@distcaribe.co",
  "telefono": "3001234567"
}
```

**Respuesta 201** — `ClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 409 | texto | Ya existe un cliente con ese tipo y número de documento |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/clientes/codigo/{codigo}`

Busca un cliente por su `codigo_cliente`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `codigo` | entero | sí |  |

**Respuesta 200** — `ClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Cliente no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/clientes/{cliente_id}`

Detalle de un cliente por su `id`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | uuid | sí |  |

**Respuesta 200** — `ClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Cliente no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/clientes/{cliente_id}`

Modifica un cliente (solo los campos enviados). `tipo_documento` y `numero_documento` van juntos.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre` | texto | no | máx. 150 caracteres; mín. 2 caracteres; puede ser `null` |
| `tipo_documento` | enum | no | valores: `CC`, `CE`, `NIT`, `PAS`; puede ser `null` |
| `numero_documento` | texto | no | máx. 30 caracteres; mín. 3 caracteres; puede ser `null` |
| `email` | texto | no | máx. 150 caracteres; puede ser `null` |
| `telefono` | texto | no | máx. 30 caracteres; puede ser `null` |
| `direccion` | texto | no | máx. 255 caracteres; puede ser `null` |
| `activo` | booleano | no | puede ser `null` |

Ejemplo:

```json
{
  "nombre": "Montería",
  "tipo_documento": "NIT",
  "numero_documento": "900123456-7",
  "email": "contacto@distcaribe.co",
  "telefono": "3001234567",
  "direccion": "Calle 10 # 5-20",
  "activo": true
}
```

**Respuesta 200** — `ClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Cliente no encontrado |
| 409 | texto | Ya existe un cliente con ese tipo y número de documento |
| 422 | texto | `tipo_documento` y `numero_documento` deben enviarse juntos |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.3 Ubicaciones (catálogo de lugares)

Ciudades de Colombia y capitales sudamericanas. Origen y destino de un envío se eligen de aquí (por `id` o por `codigo`). Para un selector del formulario use `GET /ubicaciones?q=` y `GET /ubicaciones/paises`.


#### `GET /api/v1/ubicaciones`

Lista ubicaciones. Filtros: `q` (nombre o inicio del código), `pais` (código, ej. `CO`), `tipo`, `incluir_inactivas`, `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `q` | texto | no | puede ser `null` |
| `pais` | texto | no | puede ser `null` |
| `tipo` | texto | no | puede ser `null` |
| `incluir_inactivas` | booleano | no | por defecto `false` |
| `limite` | entero | no | ≥ 1; ≤ 100; por defecto `10` |

**Respuesta 200** — lista de `UbicacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/ubicaciones`

Agrega una ubicación al catálogo.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre` | texto | sí | máx. 100 caracteres; mín. 2 caracteres |
| `departamento` | texto | sí | máx. 100 caracteres; mín. 2 caracteres |
| `pais` | texto | sí | máx. 60 caracteres; mín. 2 caracteres |
| `codigo_pais` | texto | sí | máx. 2 caracteres; mín. 2 caracteres |
| `latitud` | número | sí | ≥ -90; ≤ 90 |
| `longitud` | número | sí | ≥ -180; ≤ 180 |
| `tipo` | enum | no | valores: `ciudad`, `capital`, `puerto`; por defecto `"ciudad"` |
| `codigo` | texto | no | máx. 12 caracteres; mín. 3 caracteres; puede ser `null` |

Ejemplo:

```json
{
  "nombre": "Montería",
  "departamento": "Córdoba",
  "pais": "Colombia",
  "codigo_pais": "CO",
  "latitud": 8.7479,
  "longitud": -75.8814,
  "tipo": "ciudad",
  "codigo": "CO-MTR"
}
```

**Respuesta 201** — `UbicacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 409 | texto | Ya existe esa ubicación (mismo país, nombre y departamento) o el código está repetido |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/ubicaciones/paises`

Países que tienen ubicaciones activas, con su total. Sirve para filtros. Devuelve `[{codigo_pais, pais, total}]`.

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `codigo_pais` | string | Código ISO de 2 letras |
| `pais` | string | Nombre |
| `total` | integer | Ubicaciones activas |

Ejemplo:

```json
[
  {
    "codigo_pais": "CO",
    "pais": "Colombia",
    "total": 40
  }
]
```

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/ubicaciones/codigo/{codigo}`

Busca una ubicación por su código (por ejemplo `CO-MTR`).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `codigo` | texto | sí |  |

**Respuesta 200** — `UbicacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ubicación no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/ubicaciones/{ubicacion_id}`

Detalle de una ubicación por su `id`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ubicacion_id` | uuid | sí |  |

**Respuesta 200** — `UbicacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ubicación no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/ubicaciones/{ubicacion_id}`

Modifica una ubicación (por ejemplo para desactivarla).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ubicacion_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `departamento` | texto | no | máx. 100 caracteres; mín. 2 caracteres; puede ser `null` |
| `tipo` | enum | no | valores: `ciudad`, `capital`, `puerto`; puede ser `null` |
| `activo` | booleano | no | puede ser `null` |

Ejemplo:

```json
{
  "departamento": "Córdoba",
  "tipo": "camion",
  "activo": true
}
```

**Respuesta 200** — `UbicacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ubicación no encontrada |
| 409 | texto | Ya existe una ubicación con ese departamento |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.4 Vehículos

Flota. Un vehículo se identifica por su `placa` (única). Tipos: `furgoneta`, `camion`, `tractocamion`.


#### `GET /api/v1/vehiculos`

Lista todos los vehículos.

**Respuesta 200** — lista de `VehiculoOut` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


#### `POST /api/v1/vehiculos`

Registra un vehículo. La placa debe ser única.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `placa` | texto | sí |  |
| `tipo` | texto | sí |  |
| `capacidad_kg` | decimal | sí | > 0 |
| `capacidad_m3` | decimal | no | puede ser `null` |
| `anio` | entero | no | puede ser `null` |
| `vencimiento_seguro` | fecha | no | puede ser `null` |
| `estado` | texto | no | por defecto `"active"` |
| `capacidad_refrigeracion` | booleano | no | por defecto `false` |
| `certificado_hazmat` | booleano | no | por defecto `false` |
| `capacidad_tanque_l` | decimal | no | > 0; puede ser `null` |
| `consumo_km_por_litro` | decimal | no | > 0; puede ser `null` |
| `tipo_combustible` | texto | no | puede ser `null` |
| `ubicacion_id` | uuid | **sí** | `id` de la ubicación elegida en la lista `GET /api/v1/ubicaciones` |
| `ubicacion_nombre` | texto | **sí** | `nombre` de esa ubicación |
| `latitud` | decimal | **sí** | `latitud` de esa ubicación (−90 a 90); no se escribe a mano |
| `longitud` | decimal | **sí** | `longitud` de esa ubicación (−180 a 180); no se escribe a mano |
| `codigo_pais` | texto | **sí** | `codigo_pais` de esa ubicación (2 letras) |

La ubicación es la base donde está el vehículo: queda registrada como ubicación confiable (`ubicacion_fuente = "registro_gestor"`), el vehículo aparece en el mapa y se puede asignar por cercanía desde el primer momento. Para un vehículo creado antes sin ubicación, se fija con `PUT /api/v1/vehiculos/{id}/ubicacion` enviando los mismos campos (`ubicacion_id`, `nombre`, `latitud`, `longitud`, `codigo_pais`).

Ejemplo:

```json
{
  "placa": "GOQ998",
  "tipo": "camion",
  "capacidad_kg": 3000.0,
  "capacidad_m3": 20.0,
  "anio": 2022,
  "vencimiento_seguro": "2026-10-11",
  "estado": "active",
  "capacidad_refrigeracion": false,
  "certificado_hazmat": false,
  "capacidad_tanque_l": 100.0,
  "consumo_km_por_litro": 4.5,
  "tipo_combustible": "diesel",
  "ubicacion_id": "9322538e-829d-41a0-a45c-b8def0665556",
  "ubicacion_nombre": "Bogotá",
  "latitud": 4.711,
  "longitud": -74.0721,
  "codigo_pais": "CO"
}
```

**Respuesta 201** — `VehiculoOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | detalle de validación | Falta alguno de los campos de ubicación o es inválido (latitud/longitud fuera de rango, `codigo_pais` que no tiene 2 letras) |
| 409 | texto | Ya existe un vehículo con esa placa |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/vehiculos/placa/{placa}`

Busca un vehículo por placa.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `placa` | texto | sí |  |

**Respuesta 200** — `VehiculoOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Vehículo no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/vehiculos/{vehicle_id}`

Detalle de un vehículo por su `id`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehicle_id` | texto | sí |  |

**Respuesta 200** — `VehiculoOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Vehículo no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/vehiculos/{vehicle_id}`

Modifica datos del vehículo (solo los campos enviados).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehicle_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `tipo` | texto | no | puede ser `null` |
| `capacidad_kg` | decimal | no | > 0; puede ser `null` |
| `capacidad_m3` | decimal | no | puede ser `null` |
| `anio` | entero | no | puede ser `null` |
| `vencimiento_seguro` | fecha | no | puede ser `null` |
| `capacidad_refrigeracion` | booleano | no | puede ser `null` |
| `certificado_hazmat` | booleano | no | puede ser `null` |
| `capacidad_tanque_l` | decimal | no | > 0; puede ser `null` |
| `consumo_km_por_litro` | decimal | no | > 0; puede ser `null` |
| `tipo_combustible` | texto | no | puede ser `null` |

Ejemplo:

```json
{
  "tipo": "camion",
  "capacidad_kg": 3000.0,
  "capacidad_m3": 20.0,
  "anio": 2022,
  "vencimiento_seguro": "2026-10-11",
  "capacidad_refrigeracion": false,
  "certificado_hazmat": false,
  "capacidad_tanque_l": 100.0,
  "consumo_km_por_litro": 4.5,
  "tipo_combustible": "diesel"
}
```

**Respuesta 200** — `VehiculoOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Vehículo no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/vehiculos/{vehicle_id}/estado`

Cambia el estado del vehículo. Estados: `active` (libre), `en_transito`, `en_mantenimiento`, `fuera_de_servicio`. No lo use para asignar viajes: la asignación es automática.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehicle_id` | texto | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | texto | sí |  |

Ejemplo:

```json
{
  "estado": "en_mantenimiento"
}
```

**Respuesta 200** — `VehiculoOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Vehículo no encontrado |
| 422 | texto | El estado no es uno de los permitidos (el texto del error los lista) |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.5 Conductores

Cada conductor queda ligado de forma permanente a un vehículo (`PUT /conductores/{id}/vehiculo`). Al ligarlos se valida la licencia, la experiencia y, si aplica, la certificación HAZMAT.


#### `GET /api/v1/conductores`

Lista todos los conductores.

**Respuesta 200** — lista de `ConductorOut` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


#### `POST /api/v1/conductores`

Registra un conductor. `codigo_conductor` lo asigna el sistema (desde 1000000001).

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre` | texto | sí |  |
| `licencia_numero` | texto | sí |  |
| `categorias_licencia` | texto | no | puede ser `null` |
| `certificacion_hazmat` | booleano | no | por defecto `false` |
| `anios_experiencia` | entero | no | ≥ 0; por defecto `0` |
| `vehiculo_id` | uuid | no | puede ser `null` |
| `horas_semanales` | decimal | no | por defecto `0` |
| `estado` | texto | no | por defecto `"available"` |

Ejemplo:

```json
{
  "nombre": "Montería",
  "licencia_numero": "LIC-123456",
  "categorias_licencia": "C2",
  "certificacion_hazmat": false,
  "anios_experiencia": 5,
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "horas_semanales": 40,
  "estado": "available"
}
```

**Respuesta 201** — `ConductorOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 409 | texto | Licencia repetida o vehículo ya ocupado por otro conductor |
| 422 | `{mensaje, errores[]}` | El conductor no es elegible para ese vehículo (licencia, experiencia o HAZMAT); `errores` lista los motivos |
| 404 | texto | Vehículo no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/conductores/auditoria-vinculos`

Revisa cada vínculo conductor↔vehículo contra las reglas actuales de elegibilidad. Devuelve una lista de `{codigo_conductor, nombre, placa, tipo, valido, errores}`.

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `codigo_conductor` | integer |  |
| `nombre` | string |  |
| `placa` | string |  |
| `tipo` | string | Tipo de vehículo |
| `valido` | boolean | Cumple las reglas actuales |
| `errores` | [string] | Motivos si no cumple |

Ejemplo:

```json
[
  {
    "codigo_conductor": 1000000003,
    "nombre": "Francisco",
    "placa": "GOQ998",
    "tipo": "camion",
    "valido": true,
    "errores": []
  }
]
```

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/conductores/codigo/{codigo}`

Busca un conductor por su `codigo_conductor`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `codigo` | entero | sí |  |

**Respuesta 200** — `ConductorOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Conductor no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/conductores/{conductor_id}`

Detalle de un conductor por su `id`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `conductor_id` | uuid | sí |  |

**Respuesta 200** — `ConductorOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Conductor no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/conductores/{conductor_id}`

Modifica datos del conductor (solo los campos enviados).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `conductor_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre` | texto | no | puede ser `null` |
| `categorias_licencia` | texto | no | puede ser `null` |
| `certificacion_hazmat` | booleano | no | puede ser `null` |
| `anios_experiencia` | entero | no | ≥ 0; puede ser `null` |
| `horas_semanales` | decimal | no | puede ser `null` |

Ejemplo:

```json
{
  "nombre": "Montería",
  "categorias_licencia": "C2",
  "certificacion_hazmat": false,
  "anios_experiencia": 5,
  "horas_semanales": 40
}
```

**Respuesta 200** — `ConductorOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Conductor no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PUT /api/v1/conductores/{conductor_id}/vehiculo`

Liga el conductor a un vehículo de forma permanente (un conductor, un vehículo). Valida categoría de licencia, años de experiencia y certificación HAZMAT.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `conductor_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |

Ejemplo:

```json
{
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2"
}
```

**Respuesta 200** — `ConductorOut` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Conductor no encontrado |
| 404 | texto | Vehículo no encontrado |
| 409 | texto | El conductor ya tiene vehículo (el vínculo es permanente) o el vehículo ya tiene otro conductor |
| 422 | `{mensaje, errores[]}` | El conductor no es elegible para ese vehículo (licencia, experiencia o HAZMAT); `errores` lista los motivos |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.6 Viabilidad y reservas de flota

Las reservas las crea el sistema automáticamente (Routing); desde el frontend solo se consulta. `POST /viabilidad` sirve para avisar al usuario, antes de enviar el formulario, si algún vehículo de la flota podría transportar la carga.


#### `POST /api/v1/viabilidad`

Pregunta si **alguna** pareja vehículo+conductor de la flota podría transportar esa carga. No reserva nada. `viable=false` trae `causa` y `mensaje`. `compatibles` cuenta las parejas posibles (aunque estén ocupadas); `disponibles_ahora`, las que están libres en este momento.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `peso_kg` | decimal | sí | > 0 |
| `volumen_m3` | decimal | no | > 0; puede ser `null` |
| `tipo_carga` | enum | no | valores: `general`, `refrigerada`; por defecto `"general"` |
| `es_hazmat` | booleano | no | por defecto `false` |

Ejemplo:

```json
{
  "peso_kg": 1200,
  "volumen_m3": 8.5,
  "tipo_carga": "general",
  "es_hazmat": false
}
```

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `viable` | boolean | `true` si alguna pareja podría llevar la carga |
| `causa` | string \| null | Si no es viable: `SIN_FLOTA_OPERATIVA`, `CAPACIDAD_EXCEDIDA`, `VOLUMEN_EXCEDIDO`, `SIN_REFRIGERACION` o `SIN_HABILITACION_HAZMAT` |
| `mensaje` | string \| null | Texto listo para mostrar al usuario |
| `compatibles` | integer | Parejas vehículo+conductor que cumplen, estén libres u ocupadas |
| `disponibles_ahora` | integer | De esas, las que están libres en este momento |

Ejemplo:

```json
{
  "viable": true,
  "causa": null,
  "mensaje": null,
  "compatibles": 3,
  "disponibles_ahora": 2
}
```

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/reservas/envio/{envio_id}`

Reserva de flota más reciente de un envío: qué vehículo y conductor se le reservaron y si sigue vigente (`reservada`) o ya se liberó (`liberada`).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `reserva_id / envio_id` | uuid | Identificadores de la reserva y del envío |
| `estado` | string | `reservada` (vigente) o `liberada` |
| `vehiculo` | objeto | `{id, placa, tipo, capacidad_kg}` |
| `conductor` | objeto | `{id, codigo_conductor, nombre}` |
| `creado_en / liberado_en` | date-time \| null | Cuándo se reservó y cuándo se liberó |

Ejemplo:

```json
{
  "reserva_id": "f3c1…",
  "envio_id": "a81b…",
  "estado": "liberada",
  "ya_existia": false,
  "vehiculo": {
    "id": "5d2e…",
    "placa": "GOQ998",
    "tipo": "camion",
    "capacidad_kg": 3000.0
  },
  "conductor": {
    "id": "9b7a…",
    "codigo_conductor": 1000000003,
    "nombre": "Francisco"
  },
  "creado_en": "2026-10-11T14:02:10",
  "liberado_en": "2026-10-11T14:05:31"
}
```

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ese envío no tiene reservas |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.7 Envíos

Recurso central. Al crear un envío el sistema reserva vehículo y conductor, arranca el viaje y lo entrega solo; el frontend normalmente solo crea y consulta.


#### `GET /api/v1/envios`

Lista envíos. Filtros opcionales: `estado` y `cliente_id`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | texto | no | puede ser `null` |
| `cliente_id` | uuid | no | puede ser `null` |

**Respuesta 200** — lista de `EnvioLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/envios`

**Crea un envío y dispara todo el flujo automático.** Origen y destino se envían por id o por código (uno de los dos). `es_internacional` se deduce de los países (si lo envía y contradice las ubicaciones, 422). Antes de guardar se verifica que exista una ruta por carretera y que algún vehículo de la flota pueda con la carga. Queda `pendiente` y en segundos pasa solo a `asignado` (o `sin_asignacion` si no hay vehículo libre).

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | uuid | no | puede ser `null` |
| `codigo_cliente` | entero | no | puede ser `null` |
| `origen_id` | uuid | no | puede ser `null` |
| `origen_codigo` | texto | no | máx. 12 caracteres; puede ser `null` |
| `destino_id` | uuid | no | puede ser `null` |
| `destino_codigo` | texto | no | máx. 12 caracteres; puede ser `null` |
| `fecha_limite_sla` | fecha-hora | no | puede ser `null` |
| `es_internacional` | booleano | no | puede ser `null` |
| `peso_kg` | decimal | sí | > 0 |
| `volumen_m3` | decimal | no | ≥ 0; puede ser `null` |
| `tipo_carga` | enum | no | valores: `general`, `refrigerada`; por defecto `"general"` |
| `es_hazmat` | booleano | no | por defecto `false` |

Ejemplo:

```json
{
  "codigo_cliente": 1000000006,
  "origen_codigo": "CO-MTR",
  "destino_codigo": "CO-CTG",
  "peso_kg": 800,
  "volumen_m3": 6,
  "tipo_carga": "general",
  "es_hazmat": false
}
```

**Respuesta 201** — `EnvioLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | texto | El cliente no existe o está inactivo (regístrelo primero en `POST /clientes`) |
| 422 | texto | Origen o destino inexistentes, inactivos o iguales |
| 422 | texto | `es_internacional` contradice las ubicaciones |
| 422 | `{codigo: "SIN_CARRETERA", mensaje}` | No existe camino por tierra entre origen y destino |
| 422 | `{codigo: "CAPACIDAD_EXCEDIDA", mensaje}` | Ningún vehículo de la flota soporta ese peso |
| 422 | `{codigo: "VOLUMEN_EXCEDIDO", mensaje}` | Ningún vehículo soporta ese volumen |
| 422 | `{codigo: "SIN_REFRIGERACION", mensaje}` | Carga refrigerada y ningún vehículo con refrigeración |
| 422 | `{codigo: "SIN_HABILITACION_HAZMAT", mensaje}` | Carga HAZMAT y ninguna pareja vehículo+conductor habilitada |
| 422 | `{codigo: "SIN_FLOTA_OPERATIVA", mensaje}` | No hay vehículos operativos con conductor |
| 503 | `{codigo: "ROUTING_NO_DISPONIBLE", mensaje}` | El servicio de rutas no responde; reintente en unos segundos |
| 502 | `{codigo: "ROUTING_ERROR", mensaje}` | El servicio de rutas respondió con un error inesperado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/envios/codigo/{codigo_envio}`

Busca un envío por su código (`ENV-00000032`).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `codigo_envio` | texto | sí |  |

**Respuesta 200** — `EnvioLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Envío no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/envios/{envio_id}`

Detalle de un envío, con la asignación (vehículo, conductor, ruta, hora estimada) cuando ya existe.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `EnvioLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Envío no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/envios/{envio_id}/eventos`

Bitácora del envío (línea de tiempo): creado, asignado, en tránsito, retenido, entregado, etc., en orden.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — lista de `EnvioEventoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Envío no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/envios/{envio_id}/prueba-entrega`

Prueba de entrega del envío. `simulada=true` indica que la generó el sistema al llegar el vehículo.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `PruebaEntregaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Este envío aún no tiene prueba de entrega |
| 404 | texto | Envío no encontrado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/envios/{envio_id}/prueba-entrega`

Registra una prueba de entrega manual y deja el envío `entregado`. Solo si el envío está `asignado`, `en_transito` o `con_incidencia`. Normalmente no hace falta: el sistema entrega solo al llegar.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre_receptor` | texto | sí | máx. 150 caracteres |
| `url_firma` | texto | no | puede ser `null` |
| `url_foto` | texto | no | puede ser `null` |

Ejemplo:

```json
{
  "nombre_receptor": "María Pérez",
  "url_firma": null,
  "url_foto": null
}
```

**Respuesta 201** — `PruebaEntregaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Envío no encontrado |
| 409 | texto | Este envío ya tiene una prueba de entrega registrada |
| 409 | `{codigo: "TRANSICION_INVALIDA", mensaje}` | El envío no está en `asignado`, `en_transito` ni `con_incidencia` |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/envios/{envio_id}/reintentar-asignacion`

Pide reintentar ya la asignación de un envío que espera vehículo (`pendiente` o `sin_asignacion`). Responde `{envio_id, codigo_envio, estado_asignacion, detalle, nota}`; el estado del envío se actualiza en unos segundos.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `envio_id / codigo_envio` | uuid / string | Envío consultado |
| `estado_asignacion` | string | Estado de la ruta tras el intento: `asignada`, `sin_asignacion`… |
| `detalle` | string \| null | Último error o motivo de espera |
| `nota` | string | Aviso de que el estado del envío cambia en unos segundos |

Ejemplo:

```json
{
  "envio_id": "a81b…",
  "codigo_envio": "ENV-00000033",
  "estado_asignacion": "asignada",
  "detalle": null,
  "nota": "Si quedó asignada, el estado del envío se actualiza en unos segundos."
}
```

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Envío no encontrado |
| 409 | `{codigo: "NO_ESTA_EN_ESPERA", mensaje}` | El envío no está `pendiente` ni `sin_asignacion` |
| 409 | `{codigo: "SIN_SOLICITUD_EN_ROUTING", mensaje}` | Routing no tiene registrada la solicitud (se creó mientras Routing estaba caído) |
| 503 | `{codigo: "ROUTING_NO_DISPONIBLE", mensaje}` | Routing no responde |
| 502 | `{codigo: "ROUTING_ERROR", mensaje}` | Routing respondió con un error inesperado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/envios/{envio_id}/estado`

Cambio manual de estado, solo para casos excepcionales: el único estado destino aceptado es `en_transito`, `con_incidencia` o `devuelto` (opcional `notas`). Se valida contra la tabla de transiciones (sección 3) y se rechaza con 409 `TRANSICION_INVALIDA`. `devuelto` cancela el viaje y libera el vehículo.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | enum | sí | valores: `en_transito`, `con_incidencia`, `devuelto` |
| `notas` | texto | no | puede ser `null` |

Ejemplo:

```json
{
  "estado": "en_transito",
  "notas": null
}
```

**Respuesta 200** — `EnvioLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Envío no encontrado |
| 409 | `{codigo: "TRANSICION_INVALIDA", mensaje}` | La transición no está permitida desde el estado actual |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.8 Rutas maestras (trazado por carretera)

Ruta calculada una vez entre dos ubicaciones (carretera real vía OSRM) y reutilizada por todos los envíos entre ese origen y destino.


#### `POST /api/v1/rutas-maestras/calcular`

Calcula (o devuelve si ya existe) la ruta por carretera entre dos ubicaciones. 422 `SIN_CARRETERA` si no hay camino por tierra. Si el servicio de mapas no responde usa una estimación y lo marca con `fuente: "estimada"`.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `origen_id` | uuid | no | puede ser `null` |
| `origen_codigo` | texto | no | puede ser `null` |
| `destino_id` | uuid | no | puede ser `null` |
| `destino_codigo` | texto | no | puede ser `null` |

Ejemplo:

```json
{
  "origen_id": "d9c4ef2c-b8c8-5bdf-b71d-94fe2bb3b91c",
  "origen_codigo": "CO-MTR",
  "destino_id": "ab061fc2-ffe1-5196-849f-c2127c465669",
  "destino_codigo": "CO-CTG"
}
```

**Respuesta 201** — `RutaMaestraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | texto | Origen o destino no existen, están inactivos o son la misma ubicación |
| 422 | `{codigo: "SIN_CARRETERA", mensaje}` | No existe camino por tierra entre las dos ubicaciones |
| 409 | texto | No se pudo guardar la ruta maestra |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/rutas-maestras`

Lista rutas maestras. Filtros: `origen_codigo`, `destino_codigo`, `fuente` (`osrm` o `estimada`), `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `origen_codigo` | texto | no | puede ser `null` |
| `destino_codigo` | texto | no | puede ser `null` |
| `fuente` | texto | no | puede ser `null` |
| `limite` | entero | no | ≥ 1; ≤ 200; por defecto `50` |

**Respuesta 200** — lista de `RutaMaestraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/rutas-maestras/codigo/{codigo_ruta}`

Busca una ruta maestra por su código (`RUT-00000013`).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `codigo_ruta` | texto | sí |  |

**Respuesta 200** — `RutaMaestraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta maestra no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/rutas-maestras/{ruta_id}`

Detalle de una ruta maestra, con sus paradas (ciudades a 20 km o menos de la vía).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ruta_id` | uuid | sí |  |

**Respuesta 200** — `RutaMaestraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta maestra no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/rutas-maestras/{ruta_id}/geometria`

Trazado para dibujar la ruta en el mapa. Devuelve `{codigo_ruta, fuente, num_puntos, polyline, puntos}`; `puntos` es una lista de `[latitud, longitud]` lista para Leaflet/Google Maps y `polyline` la misma ruta codificada (formato Google, precisión 5).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ruta_id` | uuid | sí |  |

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `codigo_ruta` | string | Código de la ruta maestra |
| `fuente` | string | `osrm` (carretera real) o `estimada` (línea recta corregida) |
| `num_puntos` | integer | Cantidad de puntos |
| `polyline` | string | Trazado codificado (formato Google, precisión 5) |
| `puntos` | [[lat, lon]] | Mismo trazado como lista de pares `[latitud, longitud]` |

Ejemplo:

```json
{
  "codigo_ruta": "RUT-00000013",
  "fuente": "osrm",
  "num_puntos": 1840,
  "polyline": "_p~iF~ps|U…",
  "puntos": [
    [
      8.7479,
      -75.8814
    ],
    [
      8.7502,
      -75.8791
    ]
  ]
}
```

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta maestra no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/rutas-maestras/{ruta_id}/recalcular`

Vuelve a consultar el servicio de mapas y reemplaza los datos (por ejemplo para mejorar una ruta estimada). 503 si el servicio de mapas no responde.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ruta_id` | uuid | sí |  |

**Respuesta 200** — `RutaMaestraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta maestra no encontrada |
| 503 | texto | El servicio de mapas (OSRM) no está disponible |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.9 Rutas de envío (asignación)

Una ruta por envío: guarda el vehículo y conductor asignados y su estado. La crea y la mueve el sistema.


#### `GET /api/v1/rutas`

Lista rutas de envío. Filtros: `envio_id` y `estado`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | no | puede ser `null` |
| `estado` | texto | no | puede ser `null` |

**Respuesta 200** — lista de `RutaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/rutas/{ruta_id}`

Detalle de una ruta de envío.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ruta_id` | uuid | sí |  |

**Respuesta 200** — `RutaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/rutas/{ruta_id}/historial`

Historial de cambios de la ruta.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ruta_id` | uuid | sí |  |

**Respuesta 200** — lista de `HistorialRutaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/rutas/{ruta_id}/recalcular`

Recalcula la ruta manualmente (uso excepcional del operador).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `ruta_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `paradas` | lista de objeto | no | puede ser `null` |
| `distancia_km` | decimal | no | puede ser `null` |
| `hora_estimada_llegada` | fecha-hora | no | puede ser `null` |
| `motivo_recalculo` | texto | sí |  |

Ejemplo:

```json
{
  "paradas": [
    {}
  ],
  "distancia_km": 297.29,
  "hora_estimada_llegada": "2026-10-11T15:33:10Z",
  "motivo_recalculo": null
}
```

**Respuesta 200** — `RutaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ruta no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.10 Asignaciones (reintentos manuales)

El sistema ya reintenta solo cada pocos minutos; estas rutas son para un botón «reintentar ahora» del operador.


#### `POST /api/v1/asignaciones/reintentar`

Fuerza ahora un barrido general: reasigna lo que está sin asignación y publica eventos pendientes. Devuelve un resumen con conteos.

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `(objeto)` | JSON | Resumen del barrido: cuántos envíos se reasignaron, liberaron y publicaron |

Ejemplo:

```json
{
  "…": "resumen con conteos"
}
```

**Errores**: solo los generales del gateway (sección 2).


#### `POST /api/v1/asignaciones/envio/{envio_id}/reintentar`

Reintenta la asignación de un envío concreto y devuelve su ruta. 404 si el envío no tiene solicitud en Routing.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `RutaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ese envío no tiene una solicitud de asignación |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.11 Seguimiento (mapa y progreso)

Datos listos para pintar el mapa y la ficha de un viaje. Consúltelos periódicamente (polling, ver sección 5).


#### `GET /api/v1/seguimiento/flota`

Resumen de todos los viajes en curso (una fila por vehículo), pensado para el mapa general.

**Respuesta 200** — lista de `SeguimientoResumen` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/seguimiento/codigo/{codigo_envio}`

Igual que `/seguimiento/envio/{id}` pero buscando por código de envío.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `codigo_envio` | texto | sí |  |

**Respuesta 200** — `SeguimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | `{codigo: "SIN_VIAJE", mensaje}` | El envío no existe o aún no tiene viaje (está esperando vehículo) |
| 409 | `{codigo: "VIAJE_EN_PREPARACION", mensaje}` | El viaje se está preparando; reintente en unos segundos |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/seguimiento/vehiculo/{vehiculo_id}`

Seguimiento del viaje que está haciendo ahora un vehículo. 404 `SIN_VIAJE_ACTIVO` si no está en viaje.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |

**Respuesta 200** — `SeguimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | `{codigo: "SIN_VIAJE_ACTIVO", mensaje}` | El vehículo no está en un viaje ahora mismo |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/seguimiento/envio/{envio_id}`

**Ficha completa del viaje de un envío**: posición, progreso, tiempos y hora estimada, combustible, parada actual y paradas. Es el endpoint principal del mapa. 404 `SIN_VIAJE` si el envío aún no tiene viaje.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `SeguimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | `{codigo: "SIN_VIAJE", mensaje}` | El envío aún no tiene viaje (está `pendiente` o `sin_asignacion`) |
| 409 | `{codigo: "VIAJE_EN_PREPARACION", mensaje}` | El viaje se está preparando; reintente en unos segundos |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/seguimiento/envio/{envio_id}/trazado`

Trazado completo de la ruta (puntos y paradas) para dibujarlo una sola vez; no cambia durante el viaje.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `TrazadoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | `{codigo: "SIN_VIAJE", mensaje}` | El envío aún no tiene viaje |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/seguimiento/envio/{envio_id}/recorrido`

Puntos ya recorridos por el vehículo (para pintar la estela). Filtro `limite`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `limite` | entero | no | ≥ 1; ≤ 2000; por defecto `500` |

**Respuesta 200** — lista de `RecorridoPunto` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | `{codigo: "SIN_VIAJE", mensaje}` | El envío aún no tiene viaje |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.12 Simulaciones de viaje

Estado interno del simulador de cada viaje y su bitácora de eventos (paradas, recargas, pausas).


#### `GET /api/v1/simulaciones`

Lista simulaciones de viaje. Filtros: `estado` y `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | texto | no | puede ser `null` |
| `limite` | entero | no | ≤ 200; por defecto `50` |

**Respuesta 200** — lista de `SimulacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/simulaciones/envio/{envio_id}`

Estado interno de la simulación del viaje de un envío. 404 si el envío no tiene viaje.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `SimulacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Ese envío no tiene un viaje simulado |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/simulaciones/envio/{envio_id}/eventos`

Bitácora del viaje: inicio, paradas, recargas, pausas por aduana y llegada.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — lista de `SimulacionEventoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.13 Telemetría

Lecturas crudas de sensores de un vehículo (posición, velocidad, combustible, temperatura, odómetro).


#### `GET /api/v1/telemetria/{vehiculo_id}`

Lecturas de telemetría de un vehículo, de la más nueva a la más antigua. Filtros: `desde`, `hasta` (fechas ISO) y `limite`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `desde` | fecha-hora | no | puede ser `null` |
| `hasta` | fecha-hora | no | puede ser `null` |
| `limite` | entero | no | ≤ 1000; por defecto `100` |

**Respuesta 200** — lista de `LecturaTelemetriaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.14 Programas de mantenimiento

Plan de mantenimiento preventivo por vehículo.


#### `POST /api/v1/programas`

Crea un programa de mantenimiento preventivo para un vehículo.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |
| `tipo` | texto | sí |  |
| `fecha_vencimiento` | fecha-hora | no | puede ser `null` |
| `kilometraje_vencimiento` | decimal | no | puede ser `null` |
| `prioridad` | texto | no | por defecto `"media"` |

Ejemplo:

```json
{
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "tipo": "cambio_aceite",
  "fecha_vencimiento": "2026-10-11T15:30:00Z",
  "kilometraje_vencimiento": 3500,
  "prioridad": "media"
}
```

**Respuesta 201** — `ProgramaMantenimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/programas/{vehiculo_id}`

Programas de mantenimiento de un vehículo.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |

**Respuesta 200** — lista de `ProgramaMantenimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.15 Intervenciones de mantenimiento

Mantenimientos realizados a un vehículo.


#### `POST /api/v1/intervenciones`

Registra una intervención de mantenimiento realizada.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |
| `tipo` | texto | sí |  |
| `costo` | decimal | no | puede ser `null` |
| `taller` | texto | no | puede ser `null` |
| `kilometraje_en_servicio` | decimal | no | puede ser `null` |

Ejemplo:

```json
{
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "tipo": "cambio_aceite",
  "costo": 250000.0,
  "taller": "Taller Central",
  "kilometraje_en_servicio": 2900
}
```

**Respuesta 201** — `IntervencionMantenimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/intervenciones/{vehiculo_id}`

Intervenciones de mantenimiento de un vehículo.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `vehiculo_id` | uuid | sí |  |

**Respuesta 200** — lista de `IntervencionMantenimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.16 Aduanas

Los envíos internacionales generan una declaración. Mientras está en revisión el envío queda `retenido_aduana` y el viaje se pausa.


#### `GET /api/v1/declaraciones`

Lista declaraciones aduaneras. Filtro opcional `estado`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | texto | no | puede ser `null` |

**Respuesta 200** — lista de `DeclaracionAduaneraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/declaraciones/{envio_id}`

Declaración aduanera de un envío internacional.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | sí |  |

**Respuesta 200** — `DeclaracionAduaneraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Declaración no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `PATCH /api/v1/declaraciones/{declaracion_id}/estado`

Cambia el estado de la declaración (`pendiente`, `retenido`, `aprobado`; opcional `motivo_retencion`). Con `aprobado` el envío sale de `retenido_aduana` y el viaje se reanuda; con cualquier otro valor el envío queda `retenido_aduana` y el viaje se pausa.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `declaracion_id` | uuid | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `estado` | texto | sí |  |
| `motivo_retencion` | texto | no | puede ser `null` |

Ejemplo:

```json
{
  "estado": "aprobado",
  "motivo_retencion": null
}
```

**Respuesta 200** — `DeclaracionAduaneraLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Declaración no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.17 Notificaciones

Mensajes que el sistema genera por los eventos de un envío.


#### `GET /api/v1/notificaciones`

Notificaciones generadas, de la más reciente a la más antigua. Filtro `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `limite` | entero | no | ≤ 200; por defecto `50` |

**Respuesta 200** — lista de `NotificacionLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.18 Preferencias de notificación

Idioma y canal por cliente. **Se guardan en memoria del servicio y se pierden al reiniciarlo.**


#### `GET /api/v1/preferencias/{cliente_id}`

Preferencia del cliente. Si no hay ninguna, devuelve `{"idioma": "es", "canal_preferido": null}`.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | texto | sí |  |

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `idioma` | string | `es` o `en` |
| `canal_preferido` | string \| null | `sms`, `email` o `push` |

Ejemplo:

```json
{
  "idioma": "es",
  "canal_preferido": null
}
```

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/preferencias/{cliente_id}`

Guarda la preferencia de un cliente: `idioma` (`es` o `en`) y `canal_preferido` (`sms`, `email` o `push`, opcional). Devuelve lo guardado. 422 si el valor no es válido.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | texto | sí |  |

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `idioma` | texto | no | por defecto `"es"` |
| `canal_preferido` | texto | no | puede ser `null` |

Ejemplo:

```json
{
  "idioma": "es",
  "canal_preferido": "email"
}
```

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `idioma` | string | `es` o `en` |
| `canal_preferido` | string \| null | `sms`, `email` o `push` |

Ejemplo:

```json
{
  "idioma": "es",
  "canal_preferido": "email"
}
```

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | texto | `idioma` o `canal_preferido` no es un valor válido |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.19 Tarifas

Modelo de cobro por cliente.


#### `POST /api/v1/tarifas`

Define el modelo de cobro de un cliente.

**Cuerpo de la petición** (`application/json`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | uuid | sí |  |
| `modelo` | texto | sí |  |
| `valor` | decimal | sí |  |

Ejemplo:

```json
{
  "cliente_id": "8b4c37c3-3712-5102-8e34-d8b0e4de7157",
  "modelo": "por_envio",
  "valor": 150000.0
}
```

**Respuesta 201** — `TarifaClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/tarifas/{cliente_id}`

Tarifa de un cliente. 404 si no tiene configurada (se usa `por_envio` por defecto).

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | uuid | sí |  |

**Respuesta 200** — `TarifaClienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | El cliente no tiene tarifa configurada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.20 Costos de ruta

Costo calculado por cada envío entregado.


#### `GET /api/v1/costos-ruta`

Costos calculados por envío. Filtro opcional `envio_id`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `envio_id` | uuid | no | puede ser `null` |

**Respuesta 200** — lista de `CostoRutaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.21 Facturas

Facturación por periodo.


#### `GET /api/v1/facturas`

Lista facturas. Filtros: `cliente_id`, `periodo`, `estado`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `cliente_id` | uuid | no | puede ser `null` |
| `periodo` | texto | no | puede ser `null` |
| `estado` | texto | no | puede ser `null` |

**Respuesta 200** — lista de `FacturaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/facturas/{factura_id}`

Detalle de una factura.

**Parámetros de ruta**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `factura_id` | uuid | sí |  |

**Respuesta 200** — `FacturaLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 404 | texto | Factura no encontrada |
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `POST /api/v1/facturas/cerrar-periodo`

Cierra el periodo actual y genera las facturas pendientes. Devuelve la lista de facturas generadas.

**Respuesta 200** — lista de `FacturaLeer` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


### 6.22 Dashboard (analítica)

Indicadores listos para gráficas. Se alimentan de un proceso ETL periódico.


#### `GET /api/v1/dashboard/resumen`

Indicadores generales (envíos, entregas, flota, costos).

**Respuesta 200** — `ResumenEjecutivoLeer` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/dashboard/entregas-diarias`

Entregas por día. Filtro `dias` (ventana a mostrar).

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `dias` | entero | no | ≤ 365; por defecto `30` |

**Respuesta 200** — lista de `ResumenDiarioEntregasLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/dashboard/utilizacion-flota`

Utilización de la flota.

**Respuesta 200** — lista de `UtilizacionFlotaLeer` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/dashboard/costo-por-km`

Costo por kilómetro por tipo de vehículo.

**Respuesta 200** — lista de `CostoPorKmTipoVehiculoLeer` (campos y ejemplo en la sección 7).

**Errores**: solo los generales del gateway (sección 2).


#### `GET /api/v1/dashboard/eficiencia-combustible`

Eficiencia de combustible por conductor. Filtro `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `limite` | entero | no | ≤ 200; por defecto `50` |

**Respuesta 200** — lista de `EficienciaCombustibleConductorLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/dashboard/proyeccion-mantenimiento`

Mantenimientos próximos. Filtros: `dias` y `todos`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `dias` | entero | no | ≤ 3650; por defecto `90` |
| `todos` | booleano | no | por defecto `false` |

**Respuesta 200** — lista de `ProyeccionMantenimientoLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


#### `GET /api/v1/dashboard/actividad-reciente`

Últimos eventos del sistema. Filtro `limite`.

**Parámetros de consulta (query)**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `limite` | entero | no | ≤ 200; por defecto `20` |

**Respuesta 200** — lista de `ActividadRecienteLeer` (campos y ejemplo en la sección 7).

**Errores**

| HTTP | `detail` | Cuándo |
|---|---|---|
| 422 | lista | Datos con formato inválido (ver sección 2) |


### 6.23 ETL de analítica

Fuerza la actualización de los datos del dashboard.


#### `POST /api/v1/etl/ejecutar`

Fuerza ahora el ciclo ETL que alimenta el dashboard y devuelve su resultado.

**Respuesta 200**

| Campo | Tipo | Notas |
|---|---|---|
| `(objeto)` | JSON | Resultado del ciclo ETL (registros procesados por tabla) |

Ejemplo:

```json
{
  "…": "resultado del ciclo"
}
```

**Errores**: solo los generales del gateway (sección 2).


---

## 7. Modelos de respuesta

Forma exacta de los objetos que devuelven los endpoints de la sección 6. Los ejemplos tienen valores ilustrativos. En las tablas, `a.b` es un campo de un objeto anidado y `a[].b` es un campo de cada elemento de una lista. Todos los campos aparecen siempre en la respuesta (los que dicen «puede ser `null`» vienen con valor `null` cuando no aplican).


### ClienteLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `codigo_cliente` | entero |  |
| `nombre` | texto |  |
| `tipo_documento` | texto | puede ser `null` |
| `numero_documento` | texto | puede ser `null` |
| `email` | texto | puede ser `null` |
| `telefono` | texto | puede ser `null` |
| `direccion` | texto | puede ser `null` |
| `activo` | booleano |  |
| `es_historico` | booleano |  |
| `creado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "codigo_cliente": 1000000001,
  "nombre": "Montería",
  "tipo_documento": "NIT",
  "numero_documento": "900123456-7",
  "email": "contacto@distcaribe.co",
  "telefono": "3001234567",
  "direccion": "Calle 10 # 5-20",
  "activo": true,
  "es_historico": false,
  "creado_en": "2026-10-11T15:30:00Z"
}
```


### UbicacionLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `codigo` | texto |  |
| `nombre` | texto |  |
| `departamento` | texto |  |
| `pais` | texto |  |
| `codigo_pais` | texto |  |
| `latitud` | número |  |
| `longitud` | número |  |
| `tipo` | texto |  |
| `activo` | booleano |  |
| `etiqueta` | texto |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "codigo": "CO-MTR",
  "nombre": "Montería",
  "departamento": "Córdoba",
  "pais": "Colombia",
  "codigo_pais": "CO",
  "latitud": 8.7479,
  "longitud": -75.8814,
  "tipo": "ciudad",
  "activo": true,
  "etiqueta": "Montería, Córdoba (Colombia)"
}
```


### VehiculoOut

| Campo | Tipo | Notas |
|---|---|---|
| `placa` | texto |  |
| `tipo` | texto |  |
| `capacidad_kg` | texto |  |
| `capacidad_m3` | texto | puede ser `null` |
| `anio` | entero | puede ser `null` |
| `vencimiento_seguro` | fecha | puede ser `null` |
| `estado` | texto | por defecto `"active"` |
| `capacidad_refrigeracion` | booleano | por defecto `false` |
| `certificado_hazmat` | booleano | por defecto `false` |
| `capacidad_tanque_l` | texto | puede ser `null` |
| `consumo_km_por_litro` | texto | puede ser `null` |
| `tipo_combustible` | texto | puede ser `null` |
| `id` | uuid |  |

Ejemplo:

```json
{
  "placa": "GOQ998",
  "tipo": "camion",
  "capacidad_kg": "3000.00",
  "capacidad_m3": "20.00",
  "anio": 2022,
  "vencimiento_seguro": "2026-10-11",
  "estado": "active",
  "capacidad_refrigeracion": false,
  "certificado_hazmat": false,
  "capacidad_tanque_l": "100.00",
  "consumo_km_por_litro": "4.50",
  "tipo_combustible": "diesel",
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641"
}
```


### ConductorOut

| Campo | Tipo | Notas |
|---|---|---|
| `nombre` | texto |  |
| `licencia_numero` | texto |  |
| `categorias_licencia` | texto | puede ser `null` |
| `certificacion_hazmat` | booleano | por defecto `false` |
| `anios_experiencia` | entero | ≥ 0; por defecto `0` |
| `vehiculo_id` | uuid | puede ser `null` |
| `horas_semanales` | texto | por defecto `0` |
| `estado` | texto | por defecto `"available"` |
| `id` | uuid |  |
| `codigo_conductor` | entero |  |

Ejemplo:

```json
{
  "nombre": "Montería",
  "licencia_numero": "LIC-123456",
  "categorias_licencia": "C2",
  "certificacion_hazmat": false,
  "anios_experiencia": 5,
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "horas_semanales": "40.00",
  "estado": "available",
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "codigo_conductor": 1000000001
}
```


### EnvioLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `codigo_envio` | texto |  |
| `cliente_id` | uuid |  |
| `codigo_cliente` | entero | puede ser `null` |
| `origen` | texto |  |
| `destino` | texto |  |
| `origen_id` | uuid | puede ser `null` |
| `destino_id` | uuid | puede ser `null` |
| `codigo_pais_origen` | texto | puede ser `null` |
| `codigo_pais_destino` | texto | puede ser `null` |
| `estado` | texto |  |
| `fecha_limite_sla` | fecha-hora | puede ser `null` |
| `es_internacional` | booleano |  |
| `tipo_carga` | texto |  |
| `es_hazmat` | booleano |  |
| `peso_kg` | decimal |  |
| `volumen_m3` | decimal | puede ser `null` |
| `ruta_maestra_id` | uuid | puede ser `null` |
| `codigo_ruta` | texto | puede ser `null` |
| `distancia_km` | decimal | puede ser `null` |
| `duracion_horas` | decimal | puede ser `null` |
| `vehiculo_id` | uuid | puede ser `null` |
| `ruta_id` | uuid | puede ser `null` |
| `placa_vehiculo` | texto | puede ser `null` |
| `tipo_vehiculo` | texto | puede ser `null` |
| `conductor_id` | uuid | puede ser `null` |
| `conductor_nombre` | texto | puede ser `null` |
| `codigo_conductor` | entero | puede ser `null` |
| `hora_estimada_llegada` | fecha-hora | puede ser `null` |
| `motivo_sin_asignacion` | texto | puede ser `null` |
| `creado_en` | fecha-hora |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "codigo_envio": "ENV-00000032",
  "cliente_id": "8b4c37c3-3712-5102-8e34-d8b0e4de7157",
  "codigo_cliente": 1000000001,
  "origen": "Montería",
  "destino": "Cartagena",
  "origen_id": "d9c4ef2c-b8c8-5bdf-b71d-94fe2bb3b91c",
  "destino_id": "ab061fc2-ffe1-5196-849f-c2127c465669",
  "codigo_pais_origen": "CO",
  "codigo_pais_destino": "CO",
  "estado": "en_transito",
  "fecha_limite_sla": "2026-10-12T18:00:00Z",
  "es_internacional": false,
  "tipo_carga": "general",
  "es_hazmat": false,
  "peso_kg": "800.00",
  "volumen_m3": "6.00",
  "ruta_maestra_id": "11429cec-054a-5345-9137-b1fa4cfb9396",
  "codigo_ruta": "RUT-00000013",
  "distancia_km": "297.29",
  "duracion_horas": "5.10",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "ruta_id": "24cefe84-920f-5cb2-9bc6-92616d18bd9d",
  "placa_vehiculo": "GOQ998",
  "tipo_vehiculo": "camion",
  "conductor_id": "e5ca6f08-8d69-50ef-9177-5093fbe8310e",
  "conductor_nombre": "Francisco",
  "codigo_conductor": 1000000001,
  "hora_estimada_llegada": "2026-10-11T15:33:10Z",
  "motivo_sin_asignacion": null,
  "creado_en": "2026-10-11T15:30:00Z",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### EnvioEventoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `tipo_evento` | texto |  |
| `notas` | texto | puede ser `null` |
| `fecha_hora` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "tipo_evento": "asignado",
  "notas": null,
  "fecha_hora": "2026-10-11T15:30:00Z"
}
```


### PruebaEntregaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `envio_id` | uuid |  |
| `url_firma` | texto | puede ser `null` |
| `url_foto` | texto | puede ser `null` |
| `nombre_receptor` | texto |  |
| `entregado_en` | fecha-hora |  |
| `simulada` | booleano | `true` si la prueba la generó el sistema al llegar el vehículo; por defecto `false` |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "url_firma": null,
  "url_foto": null,
  "nombre_receptor": "María Pérez",
  "entregado_en": "2026-10-11T15:33:10Z",
  "simulada": false
}
```


### RutaMaestraLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `codigo_ruta` | texto |  |
| `origen` | objeto |  |
| `origen.id` | uuid |  |
| `origen.codigo` | texto |  |
| `origen.nombre` | texto |  |
| `origen.departamento` | texto |  |
| `origen.pais` | texto |  |
| `origen.codigo_pais` | texto |  |
| `origen.latitud` | número |  |
| `origen.longitud` | número |  |
| `origen.tipo` | texto |  |
| `origen.activo` | booleano |  |
| `origen.etiqueta` | texto |  |
| `destino` | objeto |  |
| `destino.id` | uuid |  |
| `destino.codigo` | texto |  |
| `destino.nombre` | texto |  |
| `destino.departamento` | texto |  |
| `destino.pais` | texto |  |
| `destino.codigo_pais` | texto |  |
| `destino.latitud` | número |  |
| `destino.longitud` | número |  |
| `destino.tipo` | texto |  |
| `destino.activo` | booleano |  |
| `destino.etiqueta` | texto |  |
| `distancia_km` | número |  |
| `duracion_horas` | número |  |
| `fuente` | texto |  |
| `estimada` | booleano |  |
| `paradas` | lista de objeto | puede ser `null` |
| `calculada_en` | fecha-hora |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "codigo_ruta": "RUT-00000013",
  "origen": {
    "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
    "codigo": "CO-MTR",
    "nombre": "Montería",
    "departamento": "Córdoba",
    "pais": "Colombia",
    "codigo_pais": "CO",
    "latitud": 8.7479,
    "longitud": -75.8814,
    "tipo": "ciudad",
    "activo": true,
    "etiqueta": "Montería, Córdoba (Colombia)"
  },
  "destino": {
    "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
    "codigo": "CO-MTR",
    "nombre": "Cartagena",
    "departamento": "Córdoba",
    "pais": "Colombia",
    "codigo_pais": "CO",
    "latitud": 10.391,
    "longitud": -75.4794,
    "tipo": "ciudad",
    "activo": true,
    "etiqueta": "Montería, Córdoba (Colombia)"
  },
  "distancia_km": 297.29,
  "duracion_horas": 5.1,
  "fuente": "osrm",
  "estimada": false,
  "paradas": [
    {}
  ],
  "calculada_en": "2026-10-11T15:30:00Z",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### RutaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `envio_id` | uuid |  |
| `estado` | texto |  |
| `vehiculo_id` | uuid | puede ser `null` |
| `conductor_id` | uuid | puede ser `null` |
| `detalle_asignacion` | — | puede ser `null` |
| `ruta_maestra_id` | uuid | puede ser `null` |
| `codigo_ruta` | texto | puede ser `null` |
| `paradas` | — | puede ser `null` |
| `distancia_km` | decimal | puede ser `null` |
| `distancia_planificada_km` | decimal | puede ser `null` |
| `hora_estimada_llegada` | fecha-hora | puede ser `null` |
| `veces_recalculada` | entero |  |
| `intentos` | entero |  |
| `ultimo_error` | texto | puede ser `null` |
| `proximo_reintento_en` | fecha-hora | puede ser `null` |
| `creado_en` | fecha-hora |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "estado": "en_curso",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "conductor_id": "e5ca6f08-8d69-50ef-9177-5093fbe8310e",
  "detalle_asignacion": null,
  "ruta_maestra_id": "11429cec-054a-5345-9137-b1fa4cfb9396",
  "codigo_ruta": "RUT-00000013",
  "paradas": null,
  "distancia_km": "297.29",
  "distancia_planificada_km": "297.29",
  "hora_estimada_llegada": "2026-10-11T15:33:10Z",
  "veces_recalculada": 0,
  "intentos": 1,
  "ultimo_error": null,
  "proximo_reintento_en": null,
  "creado_en": "2026-10-11T15:30:00Z",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### HistorialRutaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `ruta_id` | uuid |  |
| `paradas_anteriores` | — | puede ser `null` |
| `distancia_km_anterior` | decimal | puede ser `null` |
| `hora_estimada_llegada_anterior` | fecha-hora | puede ser `null` |
| `motivo_recalculo` | texto | puede ser `null` |
| `recalculado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "ruta_id": "24cefe84-920f-5cb2-9bc6-92616d18bd9d",
  "paradas_anteriores": null,
  "distancia_km_anterior": "100.50",
  "hora_estimada_llegada_anterior": "2026-10-11T15:30:00Z",
  "motivo_recalculo": null,
  "recalculado_en": "2026-10-11T15:30:00Z"
}
```


### SeguimientoResumen

| Campo | Tipo | Notas |
|---|---|---|
| `envio_id` | uuid |  |
| `codigo_envio` | texto | puede ser `null` |
| `vehiculo_id` | uuid |  |
| `placa` | texto | puede ser `null` |
| `estado` | texto |  |
| `origen` | texto | puede ser `null` |
| `destino` | texto | puede ser `null` |
| `latitud` | número | puede ser `null` |
| `longitud` | número | puede ser `null` |
| `velocidad_actual_kmh` | número | puede ser `null` |
| `progreso_pct` | número |  |
| `combustible_pct` | número | puede ser `null` |
| `hora_estimada_llegada` | fecha-hora | puede ser `null` |

Ejemplo:

```json
{
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "codigo_envio": "ENV-00000032",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "placa": "GOQ998",
  "estado": "en_curso",
  "origen": "Montería",
  "destino": "Cartagena",
  "latitud": 8.7479,
  "longitud": -75.8814,
  "velocidad_actual_kmh": 66.0,
  "progreso_pct": 41.2,
  "combustible_pct": 63.4,
  "hora_estimada_llegada": "2026-10-11T15:33:10Z"
}
```


### SeguimientoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `envio_id` | uuid |  |
| `codigo_envio` | texto | puede ser `null` |
| `codigo_ruta` | texto | puede ser `null` |
| `estado_viaje` | texto | `preparando`, `en_curso`, `pausada`, `finalizada` o `cancelada` |
| `mensaje` | texto | texto corto sobre la situación del viaje, listo para mostrar al usuario |
| `factor_tiempo` | número | cuántas veces más rápido que la realidad avanza la simulación (sección 5.4) |
| `vehiculo` | objeto |  |
| `vehiculo.id` | uuid |  |
| `vehiculo.placa` | texto | puede ser `null` |
| `vehiculo.conductor_id` | uuid | puede ser `null` |
| `vehiculo.conductor_nombre` | texto | puede ser `null` |
| `origen` | objeto | puede ser `null` |
| `origen.nombre` | texto | puede ser `null` |
| `origen.latitud` | número |  |
| `origen.longitud` | número |  |
| `destino` | objeto | puede ser `null` |
| `destino.nombre` | texto | puede ser `null` |
| `destino.latitud` | número |  |
| `destino.longitud` | número |  |
| `posicion` | objeto |  |
| `posicion.latitud` | número | puede ser `null` |
| `posicion.longitud` | número | puede ser `null` |
| `posicion.velocidad_kmh` | número | velocidad virtual del vehículo (ver sección 5.4); puede ser `null` |
| `posicion.actualizada_en` | fecha-hora | puede ser `null` |
| `progreso` | objeto |  |
| `progreso.porcentaje` | número |  |
| `progreso.km_recorridos` | número |  |
| `progreso.km_totales` | número | puede ser `null` |
| `progreso.km_restantes` | número | puede ser `null` |
| `tiempos` | objeto |  |
| `tiempos.iniciado_en` | fecha-hora | puede ser `null` |
| `tiempos.hora_estimada_llegada` | fecha-hora | hora real (de pared) estimada de llegada; puede ser `null` |
| `tiempos.llegada_en` | fecha-hora | puede ser `null` |
| `tiempos.segundos_restantes` | entero | segundos de pared que faltan para llegar; puede ser `null` |
| `combustible` | objeto |  |
| `combustible.nivel_pct` | número | puede ser `null` |
| `combustible.litros` | número | puede ser `null` |
| `combustible.capacidad_l` | número | puede ser `null` |
| `combustible.autonomia_km` | número | puede ser `null` |
| `combustible.recargas` | entero |  |
| `combustible.litros_recargados` | número |  |
| `combustible.estimado` | booleano |  |
| `parada_actual` | objeto |  |
| `parada_actual.en_parada` | booleano |  |
| `parada_actual.motivo` | texto | puede ser `null` |
| `parada_actual.hasta` | fecha-hora | puede ser `null` |
| `siguiente_parada` | objeto | próxima parada pendiente (`nombre`, `km_desde_origen`) o `null` si no quedan; puede ser `null` |
| `paradas` | lista de objeto | por defecto `[]` |
| `paradas[].nombre` | texto | puede ser `null` |
| `paradas[].km_desde_origen` | número |  |
| `paradas[].latitud` | número | puede ser `null` |
| `paradas[].longitud` | número | puede ser `null` |
| `paradas[].estado` | texto | `pasada`, `proxima` o `pendiente` |

Ejemplo:

```json
{
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "codigo_envio": "ENV-00000032",
  "codigo_ruta": "RUT-00000013",
  "estado_viaje": "en_curso",
  "mensaje": "En camino a Cartagena",
  "factor_tiempo": 120.0,
  "vehiculo": {
    "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
    "placa": "GOQ998",
    "conductor_id": "e5ca6f08-8d69-50ef-9177-5093fbe8310e",
    "conductor_nombre": "Francisco"
  },
  "origen": {
    "nombre": "Montería",
    "latitud": 8.7479,
    "longitud": -75.8814
  },
  "destino": {
    "nombre": "Cartagena",
    "latitud": 10.391,
    "longitud": -75.4794
  },
  "posicion": {
    "latitud": 8.7479,
    "longitud": -75.8814,
    "velocidad_kmh": 66.0,
    "actualizada_en": "2026-10-11T15:31:45Z"
  },
  "progreso": {
    "porcentaje": 41.2,
    "km_recorridos": 122.4,
    "km_totales": 297.29,
    "km_restantes": 174.89
  },
  "tiempos": {
    "iniciado_en": "2026-10-11T15:30:00Z",
    "hora_estimada_llegada": "2026-10-11T15:33:10Z",
    "llegada_en": null,
    "segundos_restantes": 95
  },
  "combustible": {
    "nivel_pct": 63.4,
    "litros": 63.4,
    "capacidad_l": 100.0,
    "autonomia_km": 420.0,
    "recargas": 0,
    "litros_recargados": 0.0,
    "estimado": false
  },
  "parada_actual": {
    "en_parada": false,
    "motivo": null,
    "hasta": null
  },
  "siguiente_parada": {
    "nombre": "Sincelejo",
    "km_desde_origen": 190.5
  },
  "paradas": [
    {
      "nombre": "Sincelejo",
      "km_desde_origen": 150.0,
      "latitud": 9.3047,
      "longitud": -75.3978,
      "estado": "pendiente"
    }
  ]
}
```


### TrazadoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `envio_id` | uuid |  |
| `codigo_envio` | texto | puede ser `null` |
| `codigo_ruta` | texto | puede ser `null` |
| `distancia_km` | número | puede ser `null` |
| `origen` | objeto |  |
| `origen.nombre` | texto | puede ser `null` |
| `origen.latitud` | número |  |
| `origen.longitud` | número |  |
| `destino` | objeto |  |
| `destino.nombre` | texto | puede ser `null` |
| `destino.latitud` | número |  |
| `destino.longitud` | número |  |
| `puntos` | lista de lista de número |  |
| `paradas` | lista de objeto | por defecto `[]` |
| `paradas[].nombre` | texto | puede ser `null` |
| `paradas[].km_desde_origen` | número |  |
| `paradas[].latitud` | número | puede ser `null` |
| `paradas[].longitud` | número | puede ser `null` |
| `paradas[].estado` | texto | `pasada`, `proxima` o `pendiente` |

Ejemplo:

```json
{
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "codigo_envio": "ENV-00000032",
  "codigo_ruta": "RUT-00000013",
  "distancia_km": 297.29,
  "origen": {
    "nombre": "Montería",
    "latitud": 8.7479,
    "longitud": -75.8814
  },
  "destino": {
    "nombre": "Cartagena",
    "latitud": 10.391,
    "longitud": -75.4794
  },
  "puntos": [
    [
      100.5
    ]
  ],
  "paradas": [
    {
      "nombre": "Sincelejo",
      "km_desde_origen": 150.0,
      "latitud": 9.3047,
      "longitud": -75.3978,
      "estado": "pendiente"
    }
  ]
}
```


### RecorridoPunto

| Campo | Tipo | Notas |
|---|---|---|
| `tiempo` | fecha-hora |  |
| `latitud` | número |  |
| `longitud` | número |  |
| `velocidad_kmh` | número | puede ser `null` |
| `nivel_combustible_pct` | número | puede ser `null` |
| `kilometraje_acumulado_km` | número | puede ser `null` |

Ejemplo:

```json
{
  "tiempo": "2026-10-11T15:31:45Z",
  "latitud": 8.7479,
  "longitud": -75.8814,
  "velocidad_kmh": 66.0,
  "nivel_combustible_pct": 63.4,
  "kilometraje_acumulado_km": 2922.4
}
```


### SimulacionLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `envio_id` | uuid |  |
| `codigo_envio` | texto | puede ser `null` |
| `ruta_id` | uuid |  |
| `vehiculo_id` | uuid |  |
| `conductor_id` | uuid | puede ser `null` |
| `placa` | texto | puede ser `null` |
| `conductor_nombre` | texto | puede ser `null` |
| `origen` | texto | puede ser `null` |
| `destino` | texto | puede ser `null` |
| `tipo_carga` | texto | puede ser `null` |
| `codigo_ruta` | texto | puede ser `null` |
| `estado` | texto |  |
| `progreso_pct` | número |  |
| `km_recorridos` | número |  |
| `distancia_total_km` | número | puede ser `null` |
| `duracion_horas` | número | puede ser `null` |
| `velocidad_actual_kmh` | número | puede ser `null` |
| `velocidad_promedio_kmh` | número | puede ser `null` |
| `latitud` | número | puede ser `null` |
| `longitud` | número | puede ser `null` |
| `combustible_l` | número | puede ser `null` |
| `combustible_pct` | número | puede ser `null` |
| `capacidad_tanque_l` | número | puede ser `null` |
| `consumo_km_por_litro` | número | puede ser `null` |
| `autonomia_km` | número | puede ser `null` |
| `combustible_estimado` | booleano |  |
| `litros_recargados` | número |  |
| `recargas` | entero |  |
| `siguiente_parada` | objeto | próxima parada pendiente (`nombre`, `km_desde_origen`) o `null` si no quedan; puede ser `null` |
| `paradas` | lista de objeto | puede ser `null` |
| `en_parada_hasta` | fecha-hora | puede ser `null` |
| `motivo_parada` | texto | puede ser `null` |
| `iniciado_en` | fecha-hora | puede ser `null` |
| `hora_estimada_llegada` | fecha-hora | puede ser `null` |
| `llegada_en` | fecha-hora | puede ser `null` |
| `ultima_actualizacion` | fecha-hora | puede ser `null` |
| `intentos` | entero |  |
| `ultimo_error` | texto | puede ser `null` |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "codigo_envio": "ENV-00000032",
  "ruta_id": "24cefe84-920f-5cb2-9bc6-92616d18bd9d",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "conductor_id": "e5ca6f08-8d69-50ef-9177-5093fbe8310e",
  "placa": "GOQ998",
  "conductor_nombre": "Francisco",
  "origen": "Montería",
  "destino": "Cartagena",
  "tipo_carga": "general",
  "codigo_ruta": "RUT-00000013",
  "estado": "en_curso",
  "progreso_pct": 41.2,
  "km_recorridos": 122.4,
  "distancia_total_km": 297.29,
  "duracion_horas": 5.1,
  "velocidad_actual_kmh": 66.0,
  "velocidad_promedio_kmh": 66.0,
  "latitud": 8.7479,
  "longitud": -75.8814,
  "combustible_l": 63.4,
  "combustible_pct": 63.4,
  "capacidad_tanque_l": 100.0,
  "consumo_km_por_litro": 4.5,
  "autonomia_km": 420.0,
  "combustible_estimado": false,
  "litros_recargados": 0.0,
  "recargas": 0,
  "siguiente_parada": {
    "nombre": "Sincelejo",
    "km_desde_origen": 190.5
  },
  "paradas": [
    {}
  ],
  "en_parada_hasta": "2026-10-11T15:30:00Z",
  "motivo_parada": null,
  "iniciado_en": "2026-10-11T15:30:00Z",
  "hora_estimada_llegada": "2026-10-11T15:33:10Z",
  "llegada_en": null,
  "ultima_actualizacion": "2026-10-11T15:30:00Z",
  "intentos": 1,
  "ultimo_error": null
}
```


### SimulacionEventoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `tipo` | texto |  |
| `descripcion` | texto | puede ser `null` |
| `km` | número | puede ser `null` |
| `combustible_pct` | número | puede ser `null` |
| `latitud` | número | puede ser `null` |
| `longitud` | número | puede ser `null` |
| `tiempo` | fecha-hora |  |

Ejemplo:

```json
{
  "tipo": "camion",
  "descripcion": "Llegó a la parada de Sincelejo",
  "km": 100.5,
  "combustible_pct": 63.4,
  "latitud": 8.7479,
  "longitud": -75.8814,
  "tiempo": "2026-10-11T15:31:45Z"
}
```


### LecturaTelemetriaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | entero |  |
| `tiempo` | fecha-hora |  |
| `vehiculo_id` | uuid |  |
| `latitud` | decimal |  |
| `longitud` | decimal |  |
| `velocidad_kmh` | decimal | puede ser `null` |
| `nivel_combustible_pct` | decimal | puede ser `null` |
| `temperatura_carga_c` | decimal | puede ser `null` |
| `kilometraje_acumulado_km` | decimal | puede ser `null` |
| `horas_motor` | decimal | puede ser `null` |
| `codigo_obd2` | texto | puede ser `null` |
| `temperatura_motor_c` | decimal | puede ser `null` |

Ejemplo:

```json
{
  "id": 1,
  "tiempo": "2026-10-11T15:31:45Z",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "latitud": "8.75",
  "longitud": "-75.88",
  "velocidad_kmh": "66.00",
  "nivel_combustible_pct": "63.40",
  "temperatura_carga_c": "100.50",
  "kilometraje_acumulado_km": "2922.40",
  "horas_motor": "1250.50",
  "codigo_obd2": null,
  "temperatura_motor_c": "90.00"
}
```


### ProgramaMantenimientoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `vehiculo_id` | uuid |  |
| `tipo` | texto |  |
| `fecha_vencimiento` | fecha-hora | puede ser `null` |
| `kilometraje_vencimiento` | texto | puede ser `null` |
| `prioridad` | texto |  |
| `creado_en` | fecha-hora |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "tipo": "cambio_aceite",
  "fecha_vencimiento": "2026-10-11T15:30:00Z",
  "kilometraje_vencimiento": "3500.00",
  "prioridad": "media",
  "creado_en": "2026-10-11T15:30:00Z",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### IntervencionMantenimientoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `vehiculo_id` | uuid |  |
| `tipo` | texto |  |
| `realizado_en` | fecha-hora |  |
| `costo` | texto | puede ser `null` |
| `taller` | texto | puede ser `null` |
| `kilometraje_en_servicio` | texto | puede ser `null` |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "tipo": "cambio_aceite",
  "realizado_en": "2026-10-11T15:30:00Z",
  "costo": "250000.00",
  "taller": "Taller Central",
  "kilometraje_en_servicio": "2900.00"
}
```


### DeclaracionAduaneraLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `envio_id` | uuid |  |
| `pais_origen` | texto |  |
| `pais_destino` | texto |  |
| `documentos` | lista de objeto |  |
| `estado` | texto |  |
| `motivo_retencion` | texto | puede ser `null` |
| `creado_en` | fecha-hora |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "pais_origen": "Colombia",
  "pais_destino": "Colombia",
  "documentos": [
    "factura_comercial",
    "lista_empaque"
  ],
  "estado": "aprobado",
  "motivo_retencion": null,
  "creado_en": "2026-10-11T15:30:00Z",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### NotificacionLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | texto |  |
| `destinatario_tipo` | texto |  |
| `canal` | texto |  |
| `mensaje` | texto | texto corto sobre la situación del viaje, listo para mostrar al usuario |
| `evento_origen` | texto |  |
| `referencia` | objeto |  |
| `enviado_en` | texto |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "destinatario_tipo": "cliente",
  "canal": "email",
  "mensaje": "En camino a Cartagena",
  "evento_origen": "route.assigned",
  "referencia": {},
  "enviado_en": "2026-10-11T15:30:00Z"
}
```


### TarifaClienteLeer

| Campo | Tipo | Notas |
|---|---|---|
| `cliente_id` | uuid |  |
| `modelo` | texto |  |
| `valor` | texto |  |

Ejemplo:

```json
{
  "cliente_id": "8b4c37c3-3712-5102-8e34-d8b0e4de7157",
  "modelo": "por_envio",
  "valor": "150000.00"
}
```


### CostoRutaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `ruta_id` | uuid |  |
| `envio_id` | uuid |  |
| `distancia_km` | texto |  |
| `costo_combustible` | texto |  |
| `costo_peajes` | texto |  |
| `horas_conductor` | texto |  |
| `costo_total` | texto |  |
| `creado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "ruta_id": "24cefe84-920f-5cb2-9bc6-92616d18bd9d",
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "distancia_km": "297.29",
  "costo_combustible": "180000.00",
  "costo_peajes": "45000.00",
  "horas_conductor": "5.10",
  "costo_total": "412000.00",
  "creado_en": "2026-10-11T15:30:00Z"
}
```


### FacturaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `id` | uuid |  |
| `cliente_id` | uuid |  |
| `periodo` | texto |  |
| `monto_total` | texto |  |
| `estado` | texto |  |
| `creado_en` | fecha-hora |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "id": "810136d4-77bd-5db3-9210-9cfec5f86641",
  "cliente_id": "8b4c37c3-3712-5102-8e34-d8b0e4de7157",
  "periodo": "2026-10",
  "monto_total": "1250000.00",
  "estado": "abierta",
  "creado_en": "2026-10-11T15:30:00Z",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### ResumenEjecutivoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `total_vehiculos` | entero | por defecto `0` |
| `vehiculos_en_uso` | entero | por defecto `0` |
| `flota_disponible` | entero | por defecto `0` |
| `total_conductores` | entero | por defecto `0` |
| `total_envios_historico` | entero | por defecto `0` |
| `envios_en_transito` | entero | por defecto `0` |
| `envios_entregados_historico` | entero | por defecto `0` |
| `envios_con_incidencia_historico` | entero | por defecto `0` |
| `envios_internacionales_retenidos` | entero | por defecto `0` |
| `tasa_cumplimiento_sla_global_pct` | texto | puede ser `null` |
| `facturacion_periodo_actual` | texto | puede ser `null` |
| `programas_mantenimiento_vencidos` | entero | por defecto `0` |
| `ultima_actualizacion_etl` | fecha-hora | puede ser `null` |

Ejemplo:

```json
{
  "total_vehiculos": 12,
  "vehiculos_en_uso": 3,
  "flota_disponible": 9,
  "total_conductores": 12,
  "total_envios_historico": 1,
  "envios_en_transito": 1,
  "envios_entregados_historico": 1,
  "envios_con_incidencia_historico": 1,
  "envios_internacionales_retenidos": 1,
  "tasa_cumplimiento_sla_global_pct": "92.50",
  "facturacion_periodo_actual": "1250000.00",
  "programas_mantenimiento_vencidos": 1,
  "ultima_actualizacion_etl": "2026-10-11T15:30:00Z"
}
```


### ResumenDiarioEntregasLeer

| Campo | Tipo | Notas |
|---|---|---|
| `fecha` | fecha |  |
| `total_creados` | entero |  |
| `total_entregados` | entero |  |
| `entregados_a_tiempo` | entero |  |
| `entregados_tarde` | entero |  |
| `con_incidencia` | entero |  |
| `devueltos` | entero |  |
| `tasa_cumplimiento_sla_pct` | texto | puede ser `null` |

Ejemplo:

```json
{
  "fecha": "2026-10-11",
  "total_creados": 1,
  "total_entregados": 1,
  "entregados_a_tiempo": 1,
  "entregados_tarde": 1,
  "con_incidencia": 1,
  "devueltos": 1,
  "tasa_cumplimiento_sla_pct": "92.50"
}
```


### UtilizacionFlotaLeer

| Campo | Tipo | Notas |
|---|---|---|
| `vehiculo_id` | uuid |  |
| `placa` | texto |  |
| `tipo` | texto |  |
| `en_uso` | booleano |  |
| `envio_id_actual` | uuid | puede ser `null` |
| `estado_envio_actual` | texto | puede ser `null` |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "placa": "GOQ998",
  "tipo": "camion",
  "en_uso": false,
  "envio_id_actual": "43d89ce8-2de6-5980-96ee-9b35274c6a79",
  "estado_envio_actual": "en_transito",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### CostoPorKmTipoVehiculoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `tipo_vehiculo` | texto |  |
| `num_rutas_con_costo` | entero |  |
| `distancia_total_km` | texto |  |
| `costo_total` | texto |  |
| `costo_promedio_por_km` | texto | puede ser `null` |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "tipo_vehiculo": "camion",
  "num_rutas_con_costo": 1,
  "distancia_total_km": "297.29",
  "costo_total": "412000.00",
  "costo_promedio_por_km": "1385.00",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### EficienciaCombustibleConductorLeer

| Campo | Tipo | Notas |
|---|---|---|
| `conductor_id` | uuid |  |
| `nombre_conductor` | texto |  |
| `vehiculo_id` | uuid | puede ser `null` |
| `placa_vehiculo` | texto | puede ser `null` |
| `km_recorridos` | texto | puede ser `null` |
| `combustible_consumido_pct` | texto | puede ser `null` |
| `km_por_pct_combustible` | texto | puede ser `null` |
| `clasificacion` | texto |  |
| `lecturas_analizadas` | entero |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "conductor_id": "e5ca6f08-8d69-50ef-9177-5093fbe8310e",
  "nombre_conductor": "Francisco",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "placa_vehiculo": "GOQ998",
  "km_recorridos": "122.40",
  "combustible_consumido_pct": "31.00",
  "km_por_pct_combustible": "3.20",
  "clasificacion": "eficiente",
  "lecturas_analizadas": 1,
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### ProyeccionMantenimientoLeer

| Campo | Tipo | Notas |
|---|---|---|
| `vehiculo_id` | uuid |  |
| `placa_vehiculo` | texto | puede ser `null` |
| `tipo_mantenimiento` | texto |  |
| `fecha_vencimiento` | fecha-hora | puede ser `null` |
| `dias_restantes` | entero | puede ser `null` |
| `kilometraje_vencimiento` | texto | puede ser `null` |
| `kilometraje_actual` | texto | puede ser `null` |
| `km_restantes` | texto | puede ser `null` |
| `prioridad_configurada` | texto |  |
| `urgencia` | texto |  |
| `actualizado_en` | fecha-hora |  |

Ejemplo:

```json
{
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "placa_vehiculo": "GOQ998",
  "tipo_mantenimiento": "cambio_aceite",
  "fecha_vencimiento": "2026-10-11T15:30:00Z",
  "dias_restantes": 1,
  "kilometraje_vencimiento": "3500.00",
  "kilometraje_actual": "2922.40",
  "km_restantes": "174.89",
  "prioridad_configurada": "media",
  "urgencia": "proximo",
  "actualizado_en": "2026-10-11T15:30:00Z"
}
```


### ActividadRecienteLeer

| Campo | Tipo | Notas |
|---|---|---|
| `tipo_evento` | texto |  |
| `envio_id` | uuid | puede ser `null` |
| `vehiculo_id` | uuid | puede ser `null` |
| `mensaje` | texto | texto corto sobre la situación del viaje, listo para mostrar al usuario |
| `ocurrido_en` | fecha-hora |  |

Ejemplo:

```json
{
  "tipo_evento": "envio_asignado",
  "envio_id": "33d8ae08-6412-51c0-b962-57ae8f85346c",
  "vehiculo_id": "83842143-b843-5280-ae01-02bcb5f5fef2",
  "mensaje": "En camino a Cartagena",
  "ocurrido_en": "2026-10-11T15:30:00Z"
}
```


---

## 8. Limitaciones conocidas y decisiones de diseño

Lo siguiente es comportamiento intencional o una limitación conocida; el frontend no debería tratarlo como un error.

1. **Los viajes son simulados.** La posición, la velocidad, el combustible y las paradas las produce un simulador dentro de Tracking, acelerado por `factor_tiempo` (sección 5.4). La entrega al llegar es automática y su prueba es simulada (`simulada: true`).
2. **Asignación automática.** Un envío sin vehículo libre queda `sin_asignacion` y se asigna solo al liberarse uno; no existe una cola de prioridades (el orden de espera es el de creación del envío).
3. **Se rechaza lo imposible, se espera lo ocupado.** Si ningún vehículo de la flota podría llevar la carga (peso, volumen, refrigeración, HAZMAT) el `POST /envios` responde 422 al instante. Si la flota *podría* pero está ocupada, el envío se acepta y espera. Si el servicio de flota no responde en el momento de crear el envío, el envío se acepta igual y la asignación lo resuelve después.
4. **La ETA cambia.** Hasta que arranca el viaje, `hora_estimada_llegada` es «momento de la asignación + duración de la ruta»; cuando el viaje inicia se recalcula con el viaje real.
5. **Un solo conductor por vehículo, permanente.** No hay turnos ni cambio de conductor.
6. **Consolidación de envíos** (agrupar varios envíos en un mismo vehículo en tránsito) **no está implementada**: cada envío ocupa un vehículo completo.
7. **Sin autenticación ni roles todavía** (sección 1.3). Cualquier usuario puede hacer cualquier operación.
8. **No hay endpoint de cancelación dedicado.** Para cancelar un envío se usa `PATCH /envios/{id}/estado` con `devuelto`, que además libera el vehículo.
9. **Preferencias de notificación en memoria.** `POST /preferencias/{cliente_id}` se pierde al reiniciar el servicio de notificaciones.
10. **Entrega justo en la retención.** Si Aduanas retiene un envío exactamente en el instante de llegada, la entrega automática no ocurre hasta que se libere y se registre la entrega a mano (`POST /envios/{id}/prueba-entrega`).
11. **Eventos entre servicios sin garantía total.** Todo se recupera solo (reintentos con espera creciente) salvo dos casos extremos: si la base de datos de Routing está caída justo cuando se crea un envío, ese envío queda `pendiente` y `POST /envios/{id}/reintentar-asignacion` responde 409 `SIN_SOLICITUD_EN_ROUTING`; y si el bus de mensajes falla justo al registrar una entrega, el vehículo podría quedar sin liberar. Ambos son raros y se arreglan desde el panel de operaciones.
12. **El dashboard no es en tiempo real.** Se alimenta de un proceso ETL periódico; `POST /etl/ejecutar` fuerza la actualización.

## Apéndice A. Ejemplos con `curl`

```bash
BASE=http://localhost:8002/api/v1

# Salud de los servicios
curl $BASE/estado

# ¿Algún vehículo podría llevar 800 kg?
curl -X POST $BASE/viabilidad -H "Content-Type: application/json" \
  -d '{"peso_kg": 800}'

# Buscar un cliente y una ubicación
curl "$BASE/clientes?q=distribuidora"
curl "$BASE/ubicaciones?q=monter&pais=CO"

# Crear un envío (cliente por código, ubicaciones por código)
curl -X POST $BASE/envios -H "Content-Type: application/json" \
  -d '{"codigo_cliente": 1000000006, "origen_codigo": "CO-MTR", "destino_codigo": "CO-CTG", "peso_kg": 800, "tipo_carga": "general"}'

# Ver cómo evoluciona (cambie el id por el de la respuesta anterior)
curl $BASE/envios/3f6c1b2e-8a47-4d1e-9c55-2b7a0e4d9f10
curl $BASE/seguimiento/envio/3f6c1b2e-8a47-4d1e-9c55-2b7a0e4d9f10
curl $BASE/envios/3f6c1b2e-8a47-4d1e-9c55-2b7a0e4d9f10/eventos
```

## Apéndice B. Cliente mínimo en JavaScript

```js
const BASE = 'http://localhost:8002/api/v1';

async function api(metodo, ruta, cuerpo) {
  const r = await fetch(BASE + ruta, {
    method: metodo,
    headers: cuerpo ? { 'Content-Type': 'application/json' } : undefined,
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    const error = new Error(mensajeDeError(datos, r.status));   // ver sección 2.1
    error.status = r.status;
    error.codigo = datos?.detail?.codigo;                        // p. ej. 'CAPACIDAD_EXCEDIDA'
    error.requestId = r.headers.get('X-Request-ID');
    throw error;
  }
  return datos;
}

// Crear un envío y esperar a que se asigne
async function crearYSeguir(solicitud) {
  const envio = await api('POST', '/envios', solicitud);
  for (let i = 0; i < 15; i++) {
    const actual = await api('GET', `/envios/${envio.id}`);
    if (actual.estado !== 'pendiente') return actual;
    await new Promise(res => setTimeout(res, 2000));
  }
  return envio; // sigue pendiente: mostrar «asignación en proceso»
}
```
