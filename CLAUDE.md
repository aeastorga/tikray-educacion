# Tikray Labs · Sistema para colegios

Contexto para trabajar en local con Claude Code. La fuente completa está en:
- Propuesta de módulos: https://claude.ai/artifact/DsbSwbZptatzPUsgXTzT5m
- Plan técnico del MVP: https://claude.ai/artifact/HBcrFpgHt5ETD1FxRmwtdi

## Qué es
Plataforma multi-colegio (particulares y estatales) de Tikray Labs. Eje: que el padre sepa qué pasa con su hijo sin preguntar (asistencia, avisos, cuaderno de control digital). Precio: S/ 2 por alumno al mes + pago inicial por equipos, instalación y capacitación.

## Reglas que no se rompen
- `colegio_id` en todas las tablas, tomado del token, nunca del navegador. Pruebas automáticas de aislamiento entre colegios.
- Todo por configuración del director; nada de código hecho para un solo colegio.
- Solo canales gratuitos: push (PWA). WhatsApp solo como botón `wa.me` con mensaje prellenado. Sin WhatsApp Business API ni SMS.
- La marcación solo guarda y responde (< 300 ms); los avisos salen en segundo plano desde una cola en la base de datos.
- Fechas en UTC, mostradas en hora de Lima. Faltas automáticas solo en días lectivos (calendario de días no lectivos).
- Datos biométricos nunca pasan por el servidor: el terminal envía solo código del alumno, hora y equipo.
- Ley 29733: colegio = titular de los datos, Tikray Labs = encargado. Consentimiento del apoderado guardado con fecha.

## Stack
- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (servidor que no se suspenda).
- Frontend: una app React + Vite (PWA) con tres espacios: panel del colegio, docente/portería, familia. Más el panel de Tikray Labs.
- Colegio identificado por subdominio (`colegio.plataforma.pe`) o dominio propio opcional. Logo y colores libres.
- Archivos (fotos, adjuntos) en almacenamiento tipo S3, no en la base.

## Portal y accesos
- Una dirección por colegio, pantalla de ingreso con dos botones: "Soy padre o apoderado" y "Soy personal del colegio".
- Personal: usuario (DNI por defecto) + clave temporal que se cambia al primer ingreso. Roles propios creados por el director, permisos por módulo.
- Padres: sin registro abierto. Enlace personal de un solo uso (vence en 7 días, se bloquea tras 5 intentos) enviado por WhatsApp desde el colegio + DNI del alumno y del padre → PIN o huella del celular. Una cuenta por DNI; el enlace solo activa a ese apoderado. Activación automática o con aprobación (lo elige el director). Panel "Cuentas de padres" para invitar, aprobar, bloquear y cerrar sesiones. Respaldo: correo, carta QR o secretaría.
- Una cuenta de familia global une a los hijos aunque estén en colegios distintos.

## MVP, en este orden
0. Cimientos: repo, multi-colegio, subdominio, ingreso del personal, roles y permisos, panel de Tikray Labs, imagen del colegio, pruebas de aislamiento.
1. Padrón: año escolar, niveles, turnos y horarios, grados, secciones, calendario de días no lectivos, carga masiva Excel (hoja alumnos+apoderados, hoja personal) con vista previa de errores, carnets QR y cartas en PDF.
2. Asistencia de alumnos y personal: portería con QR (funciona sin internet), receptor único de marcaciones, tardanza por turno, faltas automáticas, deduplicación de doble marcación, marcación manual sin carnet, licencias del personal, reportes.
3. Familias y avisos: activación, PIN, passkeys, push, cola de envío, avisos de ingreso/tarde/falta/salida, tarjeta en vivo, estado de avisos por padre. Opción adicional "modo reunión": QR por aula (válido unas horas) para que el padre llene su ficha y consentimiento; queda pendiente hasta que el tutor la aprueba en vivo y puede activar la cuenta ahí mismo; respaldo ficha PDF prellenada o tablet; no abre registro libre.
4. Cuaderno de control: comunicados con firma de lectura, incidencias, citaciones, justificaciones, permisos de salida, respuestas.
5. Panel del director y demo con datos ficticios reiniciable; prueba de carga (1000 marcaciones en 10 min).

Fase 2: huella y facial (ZKTeco ADMS, Hikvision eventos HTTP, validar con equipo de prueba), caja y gastos particular/estatal, pensiones, recojo seguro, calendario escolar, autorizaciones, notas y libreta.

## Lecciones de SGI (aeastorga/SGI)
- Apoderado ↔ alumno es N a N (en SGI era 1 a 1 y el alumno guardaba el nombre del apoderado como texto).
- Reglas en el modelo y pruebas desde el inicio, no scripts de corrección.
- Sin `SECRET_KEY` por defecto: el sistema no arranca si falta.
- Reutilizable: lógica de asistencia QR, permisos por módulo, pensiones y caja de SGI; auth, panel maestro y logo de `aeastorga/sgi-platform`.
