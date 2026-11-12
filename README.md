# Tikray Educación

Plataforma multi-colegio de Tikray Labs: asistencia de alumnos y personal, avisos a padres, cuaderno de control digital y gestión del colegio.

Ver `CLAUDE.md` para las decisiones de diseño y el orden de construcción del MVP.

## En local

Requisitos: Python 3.12, Node 22, PostgreSQL 16.

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # y completa SECRET_KEY y DATABASE_URL
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli crear-admin tu@correo.pe "Tu nombre"
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (otra terminal)
cd frontend && npm install && npm run dev
```

- Panel de Tikray Labs: http://plataforma.localhost:5173 (ahí se crean los colegios y su administrador).
- Cada colegio: http://<subdominio>.localhost:5173

## En Render (pruebas)

`render.yaml` crea un servicio web (Docker: el backend sirve también la PWA compilada) y un PostgreSQL, los dos en plan gratis. La dirección del servicio, `<nombre>.onrender.com`, es el subdominio del colegio demo (`DOMINIO_BASE=onrender.com`).

- **Migraciones**: `backend/iniciar.sh` corre `alembic upgrade head` antes de levantar uvicorn en cada despliegue; si falla, la versión nueva no recibe tráfico.
- **Secretos**: `SECRET_KEY` la genera Render; `VAPID_CLAVE_PRIVADA` y `VAPID_CLAVE_PUBLICA` se cargan en el panel (Render las pide al crear el Blueprint). Nada en el repositorio.
- **IP real**: el contenedor solo recibe tráfico del proxy de Render por su red privada; `PROXIES_CONFIANZA` acepta `X-Forwarded-For` de esas redes y toma la IP de más a la derecha que no sea de ellas. `https://<nombre>.onrender.com/salud/ip` muestra lo que llega, para comprobarlo.
- **Plan gratis**: el servicio se suspende tras 15 minutos sin visitas (tarda hasta un minuto en despertar) y mientras duerme no salen avisos ni faltas automáticas; no hay Shell (el colegio demo se crea desde tu computadora con la URL externa de la base); los archivos subidos se pierden al redesplegar; la base vence a los 30 días. Para quitar la suspensión: `plan: free` → `plan: starter` en el servicio.

## Pruebas

Corren contra PostgreSQL real (borran y recrean el esquema de la base de pruebas):

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/tikray_test .venv/bin/pytest
```

Pruebas de navegador (Playwright) de todos los módulos: levantan su propio backend (puerto 8001) y Vite (5174) contra otra base, que se borra y se siembra con datos ficticios en cada corrida (su nombre debe terminar en `e2e`):

```bash
cd frontend
npx playwright install chromium   # la primera vez
E2E_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/tikray_e2e npm run e2e
```

## Cómo se aísla cada colegio

- El colegio sale del `Host` (subdominio o dominio propio). Las rutas privadas exigen que el `colegio_id` del token sea el de ese Host; si no, 403.
- `colegio_id` es obligatorio en toda tabla, con llave foránea a `colegio`. Las relaciones internas usan llaves compuestas `(colegio_id, id)`, así la base rechaza, por ejemplo, un usuario con un rol de otro colegio.
- El personal de Tikray Labs usa otro token (firma y audiencia distintas) y solo entra a `/plataforma`.
- `tests/test_aislamiento.py` recorre todas las rutas para comprobar esto.

## Estado del colegio

`prueba`, `activo` o `suspendido`, con `vence_en` opcional (obligatorio en prueba). Vencido o suspendido, el colegio responde 403 en todas sus rutas. La fecha se compara en hora de Lima.

## Intentos de ingreso

5 fallos por cuenta y 50 por IP cada 15 minutos (todo el personal de un colegio suele salir por la misma IP). Los fallos se guardan en la base (`intento_fallido`), no en memoria: el límite vale aunque haya varias instancias del servidor y no se reinicia al reiniciarlo. No se guarda la clave intentada; las filas de más de un día se borran solas. Detrás de un proxy, configura `PROXIES_CONFIANZA` para leer la IP real de `X-Forwarded-For`.

## Padrón (paso 1)

- **Año escolar** con fechas y días de clase de la semana (lunes a viernes por defecto; se pueden agregar sábados). Un solo año activo por colegio, también controlado por la base.
- **Niveles, grados, turnos** (entrada, tolerancia y salida) y **secciones** por año.
- **Días no lectivos**: un día o un rango (vacaciones); solo se guardan los días de clase.
- **Alumnos y apoderados**: N a N (hermanos con el mismo apoderado, un alumno con varios). Documento DNI, CE, pasaporte u otro.
- **Carga masiva desde Excel**: plantilla con hojas Alumnos y Personal. La vista previa muestra los errores por hoja, fila y columna, y no se guarda nada hasta que no haya ninguno. Reimportar actualiza, no duplica.
- **Carnets en PDF** (10 por hoja A4). El QR lleva un código aleatorio (`TK1:XXXXXXXX`), no el DNI, y se puede regenerar si se pierde el carnet.
- **Cartas de acceso del personal** en PDF con usuario y clave temporal. Se generan solo al confirmar la carga y no se guardan.

## Asistencia (paso 2)

- **Portería** (`/panel/asistencia/porteria`): lee el carnet con la cámara del celular (QR) o con un lector USB, y permite marcar sin carnet buscando por nombre. Funciona sin internet: guarda el padrón (código, nombre, sección y turno; sin DNI) y las marcaciones en el celular, decide al instante entrada, salida, tardanza o doble marcación, y envía lo pendiente cuando vuelve la conexión.
- **Receptor único** `POST /api/asistencia/marcaciones` (lotes de hasta 500): portería, marcación manual y, en la fase 2, los equipos de huella o facial. Cada marcación trae un `id_cliente` generado en el dispositivo: un reenvío no la duplica. Solo guarda y responde (unos 10 ms en local; hay una prueba que exige menos de 300 ms) y deja el aviso a la familia en `cola_aviso`, que se envía en segundo plano (paso 3).
- **Reglas**: tardanza según la hora de entrada y tolerancia del turno de la sección (o del turno asignado a cada persona del personal); doble marcación dentro de N minutos (10 por defecto); falta automática N minutos después de la hora de entrada (90 por defecto), solo en días lectivos. El administrador cambia ambos valores en Asistencia → Reglas.
- **Personal**: carnet con QR propio (`TK1P:XXXXXXXX`), turno, licencias (la licencia reemplaza la falta, también si se registra después).
- **Reportes**: resumen del día por sección y detalle por alumno; personal del día; registro mensual en Excel (una hoja por sección) para alumnos y para el personal.

Las faltas automáticas las marca un hilo del servidor cada minuto (`TAREAS_EN_FONDO=true`, por defecto), pero solo para los turnos cuyo corte (entrada + minutos de falta) cayó desde la pasada anterior, no todos los colegios cada vez. Al arrancar cierra lo que ya venció hoy, y al cambiar de día termina el anterior. Si una pasada falla, la siguiente vuelve a cubrir esa ventana. Además, cada noche a las 22:00 se revisa el día completo en todos los colegios (sin avisar a las familias a esa hora): cubre un corte o una hora de entrada adelantados durante el día, turnos o matrículas creados después del corte y días no lectivos borrados. Al arrancar el servidor también revisa el día anterior, por si estaba caído a esa hora. Si el servidor estuvo caído, se puede cerrar un día a mano sin avisar a las familias:

```bash
.venv/bin/python -m app.cli faltas 2026-11-02
```

## Familias y avisos (paso 3)

- **Cuentas de padres** (`/panel/familias`, módulo "Cuentas de padres"): el colegio genera un enlace personal de un solo uso y lo envía con el botón de WhatsApp (`wa.me` con el mensaje prellenado, desde el WhatsApp del propio colegio). El enlace vence en 7 días, se bloquea tras 5 intentos y se anula si se genera otro, si cambia el celular del apoderado o si se le bloquea. Solo se guarda su hash.
- **Activación** (`/familia/activar#…`): el padre escribe el DNI de su hijo y el suyo, acepta el consentimiento (Ley 29733; se guarda la versión, la fecha y la IP) y crea un PIN de 6 números. Si ya tiene cuenta por otro colegio, escribe su PIN de siempre: la cuenta es una por DNI y une a sus hijos de todos los colegios. El administrador elige si la activación es automática o si cada cuenta espera su aprobación.
- **Ingreso**: DNI + PIN, o huella o rostro del celular (passkey, atada al dominio del colegio; cada reto sirve una sola vez). Desde el panel se puede bloquear, desbloquear, cerrar sus sesiones o enviarle un enlace para crear un PIN nuevo.
- **Bloqueo del PIN**: tras 10 PIN fallidos seguidos en un documento (en cualquier colegio), el ingreso con PIN queda bloqueado 24 horas; con huella sí puede entrar. Se guarda en la base y se le avisa por push. Un PIN correcto reinicia la cuenta y un enlace de PIN nuevo quita el bloqueo.
- **PIN nuevo con el enlace de un colegio**: cierra sus sesiones en todos los colegios y, en los otros donde estaba activo, su acceso queda pendiente (con registro en "Cambios de datos") hasta que ese colegio lo apruebe o el padre use un enlace de ese colegio. Se le avisa por push en todos sus celulares.
- **Tarjeta en vivo** de cada hijo (ingresó, llegó tarde, faltó, salió) y la lista de avisos recibidos.
- **Avisos push** (PWA): un hilo del servidor vacía `cola_aviso` cada 3 s y deja el estado por padre (le llegó, sin notificaciones, no se pudo entregar), visible en el detalle de cada apoderado. Antes de enviar una falta revisa que el alumno siga con falta. Los avisos de más de 6 horas se descartan.
- **Cambio de celular**: si una carga de Excel o el panel cambia el celular de un apoderado, queda registrado quién lo cambió; se anula su enlace pendiente y, si ya activó su cuenta, se le avisa.

## Cuaderno de control (paso 4)

- **Comunicados** (`/panel/cuaderno`, módulo "Cuaderno de control") para todo el colegio, un nivel, un grado, una sección o un alumno, con hasta 5 adjuntos (PDF, imágenes, Word, Excel; 10 MB cada uno). A quién le llega se guarda al enviarlo: una fila por alumno y apoderado (`destino_cuaderno`), aunque después cambie el padrón.
- **Firma de lectura** por apoderado: el colegio ve quién lo vio, quién firmó y quién no (y quién aún no tiene la app). Incidencias ("enterado") y citaciones (fecha, hora, lugar; "confirmo que asistiré") también se firman.
- **Justificaciones** de faltas que envía el padre (con certificado opcional) y **permisos de salida** (día, hora, quién lo recoge); el colegio los aprueba o rechaza. Lo que registra el propio colegio queda aprobado.
- **Portería**: el padrón del celular trae los permisos de salida del día, y al marcar la salida de un alumno la tarjeta muestra el permiso (o que aún no está aprobado).
- **Respuestas** en el hilo de cada entrada, del padre y del colegio. "Solo lo que espera al colegio" filtra lo pendiente de aprobar o con la última palabra de la familia.
- **Docentes**: un rol marcado "Solo ve las secciones a su cargo" solo ve y escribe lo de las secciones que se le asignan en "Docentes por sección" (requiere permiso de editar el padrón).
- **Avisos**: cada novedad (entrada nueva, respuesta del colegio, aprobación) deja un aviso `cuaderno` por apoderado con cuenta activa en `cola_aviso`; lo envía el mismo proceso de los avisos de asistencia y la notificación abre la entrada.
- **Adjuntos fuera de la base**: en `CARPETA_PRIVADA` (en producción, un bucket privado). No se sirven en `/archivos`; se descargan por `/api/cuaderno/adjuntos/{id}` o `/api/familia/cuaderno/adjuntos/{id}`, que revisan colegio, sección y destinatario. El tipo se comprueba por el contenido del archivo.
- La familia ve el cuaderno del colegio por cuya dirección entró y solo con el acceso activo.
- **Falta justificada**: al aprobar una justificación, las faltas de esos días pasan a `justificada` (también la que se marque después, y sin aviso de falta a la familia). Se ve en el día, la tarjeta de la familia y el Excel mensual (letra J). Una justificación o permiso aprobado se puede **anular** con motivo: las faltas vuelven a `falta`, salvo que otra justificación aprobada cubra el día.

Las notificaciones necesitan claves VAPID; sin ellas los avisos quedan en la cola:

```bash
.venv/bin/python -m app.cli claves-push   # copia las dos líneas al .env
```

En iPhone las notificaciones solo funcionan con la app agregada a la pantalla de inicio (iOS 16.4 o más).

## Modo reunión (ficha del apoderado)

Para la reunión de padres: el padre actualiza sus datos y da su consentimiento desde su celular, y el tutor lo aprueba ahí mismo. Módulo "Reunión de padres" (`/panel/reunion`); un rol "solo sus secciones" solo abre reuniones de sus aulas.

- **QR del aula**: el tutor abre la reunión de una sección (1 a 8 horas) y muestra el QR. El QR es `id.firma` (HMAC con `SECRET_KEY`), no se guarda en la base y cambia con "Generar otro QR". Abrir otra reunión en la misma sección cierra la anterior.
- **El padre** escanea, escribe el documento de su hijo (solo alumnos de esa sección), llena sus datos, los del otro apoderado y acepta el consentimiento. No se le muestra nada del padrón (solo el nombre de pila del alumno): quien tenga el QR y un DNI no lee los datos de la familia. Si la reenvía, reemplaza su ficha pendiente; hasta 4 fichas por alumno.
- **Sin registro libre**: el QR vence; 10 documentos equivocados por celular cada 15 minutos; con 30 (o el doble de alumnos) en total, el QR se bloquea y el tutor muestra otro. Nada entra al padrón hasta que el tutor aprueba, con el padre delante.
- **En vivo**: la pantalla del tutor se actualiza sola; las fichas nuevas se resaltan y cada dato distinto del padrón se ve tachado y marcado ("nuevo en el padrón", "ya registrado, nuevo para este alumno").
- **Aprobar** crea o actualiza al apoderado (con registro de cambios, origen `reunion`), lo une al alumno, guarda el consentimiento con la fecha en que lo dio y aplica al otro apoderado.
- **Quien tiene cuenta propia** (el que llena o el otro apoderado) no cambia su celular ni su correo desde una ficha: el tutor ve lo que escribió, pero queda lo registrado y lo pide en persona en secretaría. Así, alguien con su DNI y el del hijo no puede desviar sus avisos.
- **DNI verificado en persona**: si la ficha suma un apoderado al alumno (nuevo en el padrón o ya registrado pero no de este alumno) o cambia un celular, el tutor no puede aprobar sin marcar "Verifiqué su DNI en persona" (la API responde 422). Queda en la ficha con su nombre y hora, y en el historial de cambios del apoderado (`dni_verificado`). Con "Activar su cuenta ahora", el celular del padre pasa solo a "crea tu PIN" (o "escribe tu PIN" si ya tiene cuenta por otro colegio) y queda activo sin otra aprobación.
- **Respaldo**: tablet en modo quiosco (no guarda nada y vuelve a empezar; al aprobar, el tutor muestra un QR para que el padre active en su celular o le manda el enlace por WhatsApp); fichas en PDF prellenadas con lo del padrón para corregir y firmar, que el tutor pasa en "Ficha en papel".
- **Quién faltó**: alumnos sin ficha en esa reunión, con sus apoderados y el botón para enviarles su enlace personal por WhatsApp (`wa.me`).

## Cierre del MVP (paso 5)

- **Panel del administrador** (`/panel`, Inicio): asistencia de hoy (porcentaje, puntuales, tardanzas, faltas, justificadas, sin marcar), los últimos 10 días de clase, secciones con más faltas, personal; cuaderno (por aprobar, hilos con respuesta de la familia, firmas de los últimos comunicados y citaciones); familias (cuentas activas, con notificaciones, avisos de hoy y en cola). Cada bloque sale solo con permiso de ver ese módulo; se refresca cada minuto. `GET /api/panel/resumen`.
- **Demo con datos ficticios** que se reinicia: 25 secciones (inicial, primaria, secundaria; mañana y tarde), alumnos, apoderados (60 % con cuenta), docentes por sección, 10 días de asistencia, licencias y cuaderno, y datos de pensiones, calendario, recojo y autorizaciones. Documentos ficticios (`D…`), nunca DNI reales. Solo funciona sobre un colegio marcado `es_demo`: nunca borra uno real.

  ```bash
  .venv/bin/python -m app.cli demo demo                          # crea o reinicia demo.<dominio>
  .venv/bin/python -m app.cli demo demo --alumnos-por-seccion 40 # 1000 alumnos
  ```

  También desde el panel de Tikray Labs: "Crear colegio demo" y "Reiniciar demo" en cada colegio demo. Claves: personal `Demo2026Tikray` (administrador 90000001, portería 90000004), familia PIN `135790`.
- **Prueba de carga**: 1000 marcaciones en 10 minutos desde 4 porterías, una petición por lectura, contra el colegio demo. Falla (código 1) si hay errores o el p95 pasa de 300 ms.

  ```bash
  .venv/bin/python -m app.carga --colegio demo            # 10 minutos
  .venv/bin/python -m app.carga --colegio demo --rapido   # sin esperas
  ```

  Resultado en local (WSL2, PostgreSQL 16, un solo proceso uvicorn), 3 de noviembre de 2026, colegio demo con 1000 alumnos: 1000 marcaciones en 599 s desde 4 porterías, **p50 21 ms · p95 34 ms · p99 37 ms · máximo 70 ms**, 0 errores. Los 1549 avisos que generaron salieron de la cola en segundo plano (ninguno quedó pendiente). Sin esperas (`--rapido`), unas 95 marcaciones por segundo con p95 de 51 ms.

## Administrador y límite de usuarios

- El usuario principal de cada colegio es el **administrador** (rol marcado `es_administrador`; antes se llamaba "Director"). Lo crea Tikray Labs al crear el colegio.
- Tiene todos los permisos. Su rol no se modifica ni se borra, y solo otro administrador da o quita ese rol (también en la carga de Excel).
- Solo él ve y cambia la configuración de comprobantes SUNAT y ve el historial de actividad.
- **Límite de usuarios** (`colegio.max_usuarios`, vacío = sin límite): lo fija solo Tikray Labs según el plan. Cuentan los usuarios del personal activos, incluido el administrador; los padres no.
- Un usuario desactivado libera su cupo. Si el límite baja por debajo de los activos, no se desactiva a nadie: solo no se pueden agregar más (409) hasta bajar.

## Pensiones y caja

- **Pensiones** (`/panel/pensiones`): conceptos (matrícula, pensión, otro), montos, cronograma, generación de cuotas por alumno, descuentos y becas, retiro y reporte de morosidad. Mora opcional (fija o porcentaje, con tope).
- **Caja** (`/panel/caja`): la caja del día de cada cajero, cobros con recibo interno (efectivo, Yape, Plin, transferencia o tarjeta), cierre, gastos y reportes de ingresos y gastos.
- Módulos contratables aparte (`pensiones` y `caja`): apagados en colegios nuevos y encendidos en la demo. Con el módulo apagado todo responde 403.
- **Dinero**: montos en `Numeric(10, 2)`, nunca float. Nada se borra: pagos, cuotas, descuentos y gastos solo se anulan con motivo. El saldo de una cuota nunca queda negativo. Anular un pago de caja cerrada o un gasto de un día anterior pide ser administrador o un rol con "puede anular".
- **Familia**: el apoderado responsable de pago ve las cuotas de cada hijo, los pagos y su recibo. Recibe un aviso de cobro N días antes del vencimiento (3 por defecto) y el día que vence, por la cola. Sin pago en línea.
- La deuda nunca bloquea nada fuera de este módulo (asistencia, avisos, cuaderno, acceso de la familia).

## Comprobantes SUNAT

- Boleta o factura electrónica de los pagos de caja, lista para conectar a un proveedor. Sin proveedor (`FacturadorNinguno`, por defecto) el colegio sigue solo con el recibo interno, que se entrega siempre.
- La configuración la editan solo el administrador y Tikray Labs. El token del proveedor se guarda cifrado (`FACTURACION_CLAVE`) y nunca vuelve al navegador ni al historial.
- El cobro crea el comprobante en "pendiente" y responde sin esperar al proveedor: se emite en segundo plano desde `cola_comprobante`. Si el proveedor falla, se reintenta hasta 5 veces y después queda en "Comprobantes con error" con el botón "Reintentar".
- Número correlativo por serie y colegio, sin saltos. Nada se borra: anular el pago encola la anulación del comprobante ante el proveedor.

## Recojo seguro

- Quién puede recoger a cada alumno: sus apoderados (siempre), hasta 5 **autorizados permanentes** activos y los **autorizados del día** que da el apoderado para una fecha (vencen solos).
- El colegio (permiso `recojo`) y la familia arman la lista; lo que agrega el apoderado entra activo de inmediato. Nada se borra: un autorizado se desactiva.
- **Portería**: al marcar la salida muestra quién puede recogerlo hoy (documento con los últimos 4 dígitos) y registra quién se lo llevó. Nunca bloquea la salida: si no está en la lista, queda como "fuera de la lista", que Asistencia puede filtrar. No manda un segundo aviso.
- El recojo guarda una copia del nombre y documento: el reporte no cambia si después se edita al autorizado.
- Módulo contratable aparte (`recojo`): apagado en colegios nuevos y encendido en la demo. Ley 29733: el documento y la foto de quien recoge se usan solo para esto.

## Calendario escolar

- Eventos por año escolar (actuación, reunión de padres, examen, feriado, salida, otro) para todo el colegio, uno o varios niveles o una o varias secciones. Vista de mes y PDF del mes.
- Los días sin clases siguen en Estructura (`dia_no_lectivo`); el calendario solo los muestra.
- Un evento no se borra: se anula con motivo y queda visible como anulado.
- La familia ve solo los eventos que tocan a sus hijos y los días sin clases.
- Si se marca "avisar a las familias", sale un aviso al publicar y un recordatorio el día anterior, por la cola (respetan el horario sin molestar y se apagan en Configuración › Avisos).
- Módulo contratable aparte (`calendario`): apagado en colegios nuevos y encendido en la demo.

## Autorizaciones

- El colegio pide permiso para un paseo, el uso de fotos o una actividad, a todo el colegio, niveles, secciones o alumnos sueltos. Estados: borrador, publicada, cerrada y anulada; nada se borra.
- La familia, en su pestaña "Autorizaciones" (pendientes arriba), responde "Autorizo" o "No autorizo" por cada hijo, con un comentario opcional. Basta un apoderado y vale la última respuesta; se puede cambiar hasta la fecha límite. Después ya no se responde y "sin respuesta" no cuenta como autorizado.
- Responde solo el apoderado que recibe los avisos de ese hijo y tiene la cuenta activa. Cada respuesta queda con fecha, hora y quién respondió (Ley 29733).
- Seguimiento con cifras, lista por sección, "Recordar a los que faltan" y lista en PDF y Excel. Un docente con "solo sus secciones" solo ve y crea para sus secciones.
- Avisos por la cola al publicar y el día antes de la fecha límite solo a los que faltan (respetan el horario sin molestar y se apagan en Configuración › Avisos).
- Módulo contratable aparte (`autorizaciones`): apagado en colegios nuevos y encendido en la demo.
