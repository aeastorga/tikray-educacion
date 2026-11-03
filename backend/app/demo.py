"""Colegio de demostración con datos ficticios, que se puede reiniciar.

- Solo se crea, borra o reinicia un colegio marcado `es_demo`: nunca toca un colegio real.
- Nombres al azar de listas comunes; ningún documento es real. Los apoderados usan el tipo
  OTRO con números `D<colegio>P<n>` (sin guiones), así su cuenta de familia (que es global, una por
  documento) nunca puede coincidir con la de una persona real.
- Reiniciar = borrar todos los datos del colegio (tabla por tabla, por `colegio_id`) y volver a
  sembrarlos. El colegio (su id, subdominio, dominio propio, logo y colores) se conserva.

    python -m app.cli demo [subdominio] [--alumnos-por-seccion N]
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import codigos
from app.almacenamiento import get_almacenamiento_privado
from app.db import Base
from app.fechas import LIMA, hoy_lima
from app.models import (AdjuntoCuaderno, Alumno, AlumnoApoderado, AnioEscolar, Apoderado, AsistenciaAlumno,
                        AsistenciaPersonal, Colegio, ConfigFamilias, CuentaFamilia, DestinoCuaderno, DiaNoLectivo,
                        EntradaCuaderno, Grado, LicenciaPersonal, Matricula, MensajeCuaderno, Nivel, PermisoRol, Rol,
                        Seccion, SeccionDocente, Turno, Usuario)
from app.modulos import MODULOS
from app.seguridad import hashear_clave

CLAVE = "Demo2026Tikray"  # todo el personal de la demo
PIN = "135790"  # todas las familias con cuenta
DIRECTOR = "90000001"

NOMBRES = ["Lucía", "Mateo", "Valentina", "Santiago", "Camila", "Sebastián", "Sofía", "Thiago", "Valeria", "Gael",
           "Mía", "Liam", "Ximena", "Leonardo", "Isabella", "Adrián", "Renata", "Diego", "Antonella", "Matías",
           "Luana", "Joaquín", "Fernanda", "Gabriel", "Daniela", "Alonso", "Mariana", "Rodrigo", "Ariana", "Nicolás",
           "Kiara", "Fabricio", "Romina", "Emiliano", "Alessia", "Bruno", "Abigail", "Piero", "Nayeli", "Josué"]
ADULTOS = ["Rosa", "Juan", "María", "Carlos", "Ana", "José", "Carmen", "Luis", "Elena", "Jorge", "Patricia", "Miguel",
           "Gladys", "Víctor", "Silvia", "Pedro", "Norma", "César", "Maribel", "Raúl", "Julia", "Walter", "Yolanda",
           "Hugo", "Lourdes", "Óscar", "Teresa", "Alberto", "Marlene", "Wilber"]
APELLIDOS = ["Quispe", "Flores", "Sánchez", "Rodríguez", "García", "Mamani", "Huamán", "Chávez", "Rojas", "Vásquez",
             "Ramírez", "Torres", "Mendoza", "Castillo", "Díaz", "Gutiérrez", "Espinoza", "Ramos", "Vargas", "Condori",
             "Paredes", "Huanca", "Salazar", "Cruz", "Romero", "Aguilar", "Medina", "Silva", "Ccama", "Apaza"]

# Nivel -> (grados, secciones por grado, turno)
ESTRUCTURA = [
    ("Inicial", ["3 años", "4 años", "5 años"], ["Única"], "Mañana"),
    ("Primaria", ["1°", "2°", "3°", "4°", "5°", "6°"], ["A", "B"], "Mañana"),
    ("Secundaria", ["1°", "2°", "3°", "4°", "5°"], ["A", "B"], "Tarde"),
]
DIAS_HISTORIA = 10


class NoEsDemo(Exception):
    pass


@dataclass
class Resumen:
    colegio_id: int
    subdominio: str
    alumnos: int = 0
    apoderados: int = 0
    personal: int = 0
    credenciales: dict = field(default_factory=dict)


def _codigo(rnd: random.Random, usados: set[str]) -> str:
    """Código de carnet válido (el mismo formato que los reales), sin repetir."""
    while (c := "".join(rnd.choice(codigos.ALFABETO) for _ in range(codigos.LARGO))) in usados:
        pass
    usados.add(c)
    return c


def _doc_apoderado(colegio_id: int, n: int) -> str:
    return f"D{colegio_id:03d}P{n:05d}"


def borrar_datos(db: Session, colegio: Colegio) -> None:
    """Borra todo lo del colegio (no el colegio). Solo para demos. No hace commit."""
    if not colegio.es_demo:
        raise NoEsDemo(f"{colegio.subdominio} no es un colegio de demostración")
    cid = colegio.id
    almacen = get_almacenamiento_privado()
    for clave in db.scalars(select(AdjuntoCuaderno.clave).where(AdjuntoCuaderno.colegio_id == cid)):
        almacen.borrar(clave)
    # Los hijos antes que los padres (orden inverso de las llaves foráneas).
    for tabla in reversed(Base.metadata.sorted_tables):
        if tabla.name != "colegio" and "colegio_id" in tabla.c:
            db.execute(tabla.delete().where(tabla.c.colegio_id == cid))
    # Las cuentas de familia de la demo (documentos ficticios de este colegio). Sus passkeys caen en cascada.
    db.execute(delete(CuentaFamilia).where(CuentaFamilia.tipo_documento == "OTRO",
                                           CuentaFamilia.numero_documento.like(f"D{cid:03d}P%")))


def dias_de_clase(hasta: date, cuantos: int, no_lectivos: set[date]) -> list[date]:
    dias, d = [], hasta
    while len(dias) < cuantos:
        if d.isoweekday() <= 5 and d not in no_lectivos:
            dias.append(d)
        d -= timedelta(days=1)
    return sorted(dias)


def sembrar(db: Session, colegio: Colegio, alumnos_por_seccion: int = 24, semilla: int = 2026) -> Resumen:
    """Llena un colegio demo vacío. No hace commit."""
    if not colegio.es_demo:
        raise NoEsDemo(f"{colegio.subdominio} no es un colegio de demostración")
    rnd = random.Random(semilla)
    cid, hoy = colegio.id, hoy_lima()
    res = Resumen(cid, colegio.subdominio)

    # --- Año, calendario, estructura ---
    anio = AnioEscolar(colegio_id=cid, anio=hoy.year, inicio=date(hoy.year, 1, 1), fin=date(hoy.year, 12, 31),
                       dias_semana="12345", activo=True)
    turnos = {"Mañana": Turno(colegio_id=cid, nombre="Mañana", hora_entrada=time(7, 45), tolerancia_minutos=10,
                              hora_salida=time(13, 0)),
              "Tarde": Turno(colegio_id=cid, nombre="Tarde", hora_entrada=time(13, 0), tolerancia_minutos=10,
                             hora_salida=time(18, 0))}
    db.add_all([anio, *turnos.values()])
    db.flush()
    feriado = dias_de_clase(hoy - timedelta(days=1), 6, set())[0]  # un día de clase de la semana pasada
    db.add(DiaNoLectivo(colegio_id=cid, anio_id=anio.id, fecha=feriado, motivo="Día del maestro (demo)"))
    db.add(ConfigFamilias(colegio_id=cid, activacion="automatica"))
    secciones: list[tuple[Seccion, str, str]] = []  # (sección, etiqueta, turno)
    for orden, (nivel_nombre, grados, nombres_sec, turno) in enumerate(ESTRUCTURA):
        nivel = Nivel(colegio_id=cid, nombre=nivel_nombre, orden=orden)
        db.add(nivel)
        db.flush()
        for g_orden, g in enumerate(grados):
            grado = Grado(colegio_id=cid, nivel_id=nivel.id, nombre=g, orden=g_orden)
            db.add(grado)
            db.flush()
            for sn in nombres_sec:
                sec = Seccion(colegio_id=cid, anio_id=anio.id, grado_id=grado.id, turno_id=turnos[turno].id, nombre=sn)
                db.add(sec)
                secciones.append((sec, f"{g} {sn} {nivel_nombre}", turno))
    db.flush()

    # --- Personal y roles ---
    clave_hash = hashear_clave(CLAVE)
    roles = {
        "Director": Rol(colegio_id=cid, nombre="Director", es_director=True),
        "Subdirección": Rol(colegio_id=cid, nombre="Subdirección"),
        "Secretaría": Rol(colegio_id=cid, nombre="Secretaría"),
        "Portería": Rol(colegio_id=cid, nombre="Portería"),
        "Docente": Rol(colegio_id=cid, nombre="Docente", solo_sus_secciones=True),
    }
    permisos = {
        "Subdirección": {m: "ver" for m in MODULOS} | {"cuaderno": "editar", "asistencia": "editar"},
        "Secretaría": {"padron": "editar", "familias": "editar", "cuaderno": "editar", "asistencia": "ver",
                       "personal": "ver"},
        "Portería": {"asistencia": "editar"},
        "Docente": {"cuaderno": "editar", "asistencia": "ver"},
    }
    for nombre, rol in roles.items():
        rol.permisos = [PermisoRol(colegio_id=cid, modulo=m, nivel=n) for m, n in permisos.get(nombre, {}).items()]
    db.add_all(roles.values())
    db.flush()

    def persona(dni: str, nombres: str, apellidos: str, rol: str, turno: str | None = "Mañana") -> Usuario:
        u = Usuario(colegio_id=cid, numero_documento=dni, usuario=dni, nombres=nombres, apellidos=apellidos,
                    rol_id=roles[rol].id, clave_hash=clave_hash, debe_cambiar_clave=False,
                    turno_id=turnos[turno].id if turno else None)
        db.add(u)
        return u

    director = persona(DIRECTOR, "Carmen", "Salazar Ríos", "Director", None)
    persona("90000002", "Raúl", "Medina Paz", "Subdirección")
    persona("90000003", "Gladys", "Torres Vega", "Secretaría")
    portero = persona("90000004", "Hugo", "Ramos Ccama", "Portería")
    docentes = [persona(f"9100{i:04d}", rnd.choice(ADULTOS), f"{rnd.choice(APELLIDOS)} {rnd.choice(APELLIDOS)}",
                        "Docente", turno) for i, (_, _, turno) in enumerate(secciones, start=1)]
    db.flush()
    db.add_all([SeccionDocente(colegio_id=cid, seccion_id=s.id, usuario_id=d.id)
                for (s, _, _), d in zip(secciones, docentes)])
    res.personal = 4 + len(docentes)
    res.credenciales = {
        "director": {"usuario": DIRECTOR, "clave": CLAVE},
        "porteria": {"usuario": portero.usuario, "clave": CLAVE},
        "docente": {"usuario": docentes[3].usuario, "clave": CLAVE,
                    "seccion": secciones[3][1]},
        "familia": {"documento": None, "pin": PIN},
    }

    # --- Alumnos, apoderados y cuentas de familia ---
    pin_hash = hashear_clave(PIN)
    alumnos: list[tuple[Alumno, Seccion]] = []
    n_alumno, usados = 0, set()
    for sec, _, _ in secciones:
        for _ in range(alumnos_por_seccion):
            n_alumno += 1
            a = Alumno(colegio_id=cid, tipo_documento="OTRO", numero_documento=f"D{cid:03d}A{n_alumno:05d}",
                       nombres=rnd.choice(NOMBRES), apellidos=f"{rnd.choice(APELLIDOS).upper()} "
                                                          f"{rnd.choice(APELLIDOS).upper()}",
                       codigo=_codigo(rnd, usados))
            db.add(a)
            alumnos.append((a, sec))
    db.flush()
    db.execute(insert(Matricula), [{"colegio_id": cid, "anio_id": anio.id, "alumno_id": a.id, "seccion_id": s.id}
                                   for a, s in alumnos])
    res.alumnos = len(alumnos)

    n_apo, vinculos, apoderados = 0, [], []
    anterior = None
    for a, _ in alumnos:
        # Uno de cada diez es hermano del anterior: mismos apoderados.
        if anterior and rnd.random() < 0.1:
            vinculos += [(a.id, ap_id, par) for _, ap_id, par in anterior]
            anterior = [(a.id, ap_id, par) for _, ap_id, par in anterior]
            continue
        propios = []
        apellido_padre, apellido_madre = a.apellidos.split()[0].title(), a.apellidos.split()[-1].title()
        for parentesco, apellido in (("Madre", apellido_madre), ("Padre", apellido_padre))[:rnd.choice((1, 2, 2))]:
            n_apo += 1
            ap = Apoderado(colegio_id=cid, tipo_documento="OTRO", numero_documento=_doc_apoderado(cid, n_apo),
                           nombres=rnd.choice(ADULTOS), apellidos=f"{apellido} {rnd.choice(APELLIDOS)}",
                           celular=f"9{rnd.randint(10000000, 99999999)}")
            db.add(ap)
            apoderados.append(ap)
            propios.append((a, ap, parentesco))
        db.flush()
        anterior = [(a.id, ap.id, par) for _, ap, par in propios]
        vinculos += anterior
    db.execute(insert(AlumnoApoderado), [{"colegio_id": cid, "alumno_id": a, "apoderado_id": p, "parentesco": par}
                                         for a, p, par in vinculos])
    res.apoderados = len(apoderados)
    # Seis de cada diez ya activaron su cuenta (PIN de la demo).
    ahora = datetime.now(UTC)
    cuentas = [CuentaFamilia(tipo_documento="OTRO", numero_documento=ap.numero_documento, pin_hash=pin_hash)
               for ap in apoderados if rnd.random() < 0.6 or ap is apoderados[0]]
    db.add_all(cuentas)
    db.flush()
    por_doc = {c.numero_documento: c for c in cuentas}
    for ap in apoderados:
        if c := por_doc.get(ap.numero_documento):
            ap.cuenta_id, ap.estado_acceso, ap.activado_en = c.id, "activo", ahora - timedelta(days=rnd.randint(1, 60))
    res.credenciales["familia"]["documento"] = apoderados[0].numero_documento
    res.credenciales["familia"]["hijo"] = f"{alumnos[0][0].nombres} {alumnos[0][0].apellidos}"

    # --- Asistencia de los últimos días de clase (hoy queda libre para la portería) ---
    dias = dias_de_clase(hoy - timedelta(days=1), DIAS_HISTORIA, {feriado})
    filas = []
    for d in dias:
        for a, s in alumnos:
            turno = turnos["Tarde" if s.turno_id == turnos["Tarde"].id else "Mañana"]
            r = rnd.random()
            if r < 0.05:
                filas.append({"colegio_id": cid, "alumno_id": a.id, "fecha": d, "seccion_id": s.id,
                              "estado": "falta", "minutos_tarde": 0})
                continue
            tarde = rnd.randint(11, 40) if r < 0.13 else 0
            llegada = (datetime.combine(d, turno.hora_entrada, LIMA)
                       + timedelta(minutes=tarde or -rnd.randint(0, 25)))
            salida = datetime.combine(d, turno.hora_salida, LIMA) + timedelta(minutes=rnd.randint(0, 20))
            filas.append({"colegio_id": cid, "alumno_id": a.id, "fecha": d, "seccion_id": s.id,
                          "estado": "tarde" if tarde else "presente", "minutos_tarde": tarde,
                          "entrada": llegada, "salida": salida})
    db.execute(insert(AsistenciaAlumno), filas)
    personal = db.scalars(select(Usuario).where(Usuario.colegio_id == cid, Usuario.turno_id.is_not(None))).all()
    con_licencia = docentes[7]
    db.add(LicenciaPersonal(colegio_id=cid, usuario_id=con_licencia.id, tipo="salud", desde=dias[-2],
                            hasta=hoy + timedelta(days=2), motivo="Descanso médico (demo)",
                            registrado_por_id=director.id))
    filas_p = []
    for d in dias:
        for u in personal:
            if u.id == con_licencia.id and d >= dias[-2]:
                filas_p.append({"colegio_id": cid, "usuario_id": u.id, "fecha": d, "estado": "licencia",
                                "minutos_tarde": 0})
                continue
            turno = turnos["Tarde" if u.turno_id == turnos["Tarde"].id else "Mañana"]
            tarde = rnd.randint(11, 20) if rnd.random() < 0.05 else 0
            filas_p.append({"colegio_id": cid, "usuario_id": u.id, "fecha": d,
                            "estado": "tarde" if tarde else "presente", "minutos_tarde": tarde,
                            "entrada": datetime.combine(d, turno.hora_entrada, LIMA)
                            + timedelta(minutes=tarde or -rnd.randint(5, 30))})
    db.execute(insert(AsistenciaPersonal), filas_p)

    # --- Cuaderno ---
    _cuaderno(db, rnd, cid, director, docentes, secciones, alumnos, dias, hoy)
    return res


def _cuaderno(db, rnd, cid, director, docentes, secciones, alumnos, dias, hoy) -> None:
    from app import cuaderno

    def entrada(autor: Usuario | None, alumnos_ids: list[int], firmar: float = 0.0, apoderado_autor=None,
                hace_dias: int = 0, **campos) -> EntradaCuaderno:
        campos.setdefault("alcance", "alumno")
        e = EntradaCuaderno(colegio_id=cid, creado_por_id=autor.id if autor else None,
                            apoderado_autor_id=apoderado_autor, **campos)
        e.creado_en = datetime.now(UTC) - timedelta(days=hace_dias, minutes=rnd.randint(0, 600))
        db.add(e)
        db.flush()
        cuaderno.guardar_destinos(db, e, alumnos_ids)
        if firmar or apoderado_autor:
            for d in db.scalars(select(DestinoCuaderno).where(DestinoCuaderno.colegio_id == cid,
                                                              DestinoCuaderno.entrada_id == e.id)):
                if d.apoderado_id == apoderado_autor or rnd.random() < firmar:
                    d.visto_en = e.creado_en + timedelta(hours=rnd.randint(1, 30))
                    d.firmado_en = d.visto_en if cuaderno.requiere_firma(e) else None
                elif rnd.random() < 0.3:
                    d.visto_en = e.creado_en + timedelta(hours=rnd.randint(1, 30))
        return e

    todos = [a.id for a, _ in alumnos]
    de_seccion = {}
    for a, s in alumnos:
        de_seccion.setdefault(s.id, []).append(a.id)
    sec_p1 = secciones[3][0]  # 1° A Primaria
    entrada(director, todos, 0.7, tipo="comunicado", alcance="colegio", pide_firma=True, hace_dias=4,
            titulo="Reunión general de padres de familia",
            cuerpo="Los esperamos el viernes a las 6 p. m. en el patio principal. Se tratará el plan de "
                   "recuperación y el paseo de fin de año.")
    entrada(director, todos, 0.4, tipo="comunicado", alcance="colegio", pide_firma=False, hace_dias=1,
            titulo="Simulacro de sismo este jueves", cuerpo="El simulacro será a las 10 a. m. No es necesario "
                                                            "recoger a los alumnos.")
    entrada(docentes[3], de_seccion[sec_p1.id], 0.5, tipo="comunicado", alcance="seccion", seccion_id=sec_p1.id,
            pide_firma=True, hace_dias=2, titulo="Paseo al museo de sitio",
            cuerpo="Traer lonchera y agua. Salida 8 a. m., retorno 12 m.")
    for i, (a, s) in enumerate(rnd.sample(alumnos, 4)):
        entrada(docentes[0], [a.id], 0.5, tipo="incidencia", seccion_id=s.id, alumno_id=a.id, hace_dias=i,
                titulo=["No trajo su tarea de Matemática", "Se golpeó la rodilla en el recreo (se le dio primeros "
                        "auxilios)", "Uso del celular en clase", "Excelente participación en la feria de ciencias"][i])
    for i, (a, s) in enumerate(rnd.sample(alumnos, 2)):
        cita = datetime.combine(hoy + timedelta(days=2 + i), time(8, 30), LIMA)
        entrada(docentes[1], [a.id], 0.5, tipo="citacion", seccion_id=s.id, alumno_id=a.id, cita_en=cita,
                lugar="Dirección", hace_dias=1, titulo="Conversar sobre el rendimiento del bimestre")
    # Justificaciones: una por aprobar y una aprobada (que convierte sus faltas en justificadas).
    faltas = db.execute(select(AsistenciaAlumno.alumno_id, AsistenciaAlumno.fecha, AsistenciaAlumno.seccion_id)
                        .where(AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.estado == "falta")
                        .order_by(AsistenciaAlumno.fecha.desc()).limit(2)).all()
    for (alumno_id, fecha, seccion_id), estado in zip(faltas, ("pendiente", "aprobada")):
        apo = db.scalar(select(AlumnoApoderado.apoderado_id).where(AlumnoApoderado.colegio_id == cid,
                                                                   AlumnoApoderado.alumno_id == alumno_id).limit(1))
        e = entrada(None, [alumno_id], apoderado_autor=apo, tipo="justificacion", seccion_id=seccion_id,
                    alumno_id=alumno_id, desde=fecha, hasta=fecha, estado=estado, titulo="Estuvo con fiebre",
                    cuerpo="Adjunto la receta del centro de salud.", hace_dias=(hoy - fecha).days)
        if estado == "aprobada":
            e.resuelto_por_id, e.resuelto_en = director.id, e.creado_en + timedelta(hours=3)
            cuaderno.aplicar_justificacion(db, e)
    # Permisos de salida para hoy: uno aprobado y uno por aprobar (la portería los ve al marcar la salida).
    for (a, s), estado, hora in zip(rnd.sample(alumnos, 2), ("aprobada", "pendiente"), (time(10, 30), time(11, 0))):
        apo = db.scalar(select(AlumnoApoderado.apoderado_id).where(AlumnoApoderado.colegio_id == cid,
                                                                   AlumnoApoderado.alumno_id == a.id).limit(1))
        ap = db.get(Apoderado, apo)
        e = entrada(None, [a.id], apoderado_autor=apo, tipo="permiso_salida", seccion_id=s.id, alumno_id=a.id,
                    desde=hoy, hora_salida=hora, recoge=f"{ap.nombres} {ap.apellidos}", estado=estado,
                    titulo="Cita médica")
        if estado == "aprobada":
            e.resuelto_por_id, e.resuelto_en = director.id, datetime.now(UTC)
    # Un hilo con respuesta de la familia esperando al colegio.
    ultima = db.scalar(select(EntradaCuaderno).where(EntradaCuaderno.colegio_id == cid,
                                                     EntradaCuaderno.tipo == "incidencia")
                       .order_by(EntradaCuaderno.id).limit(1))
    apo = db.scalar(select(DestinoCuaderno.apoderado_id).where(DestinoCuaderno.colegio_id == cid,
                                                               DestinoCuaderno.entrada_id == ultima.id).limit(1))
    db.add(MensajeCuaderno(colegio_id=cid, entrada_id=ultima.id, apoderado_id=apo, de_familia=True,
                           cuerpo="Gracias por avisar. Esta semana la revisamos juntos en casa."))


def crear_o_reiniciar(db: Session, subdominio: str = "demo", nombre: str = "Colegio Demo Tikray",
                      alumnos_por_seccion: int = 24) -> Resumen:
    """Crea el colegio demo, o lo reinicia si ya existe. Si el subdominio es de un colegio real, falla.
    Hace commit."""
    colegio = db.scalar(select(Colegio).where(Colegio.subdominio == subdominio))
    if colegio is None:
        colegio = Colegio(nombre=nombre, subdominio=subdominio, es_demo=True, color_primario="#0F5257",
                          color_secundario="#F2A900")
        db.add(colegio)
        db.flush()
    else:
        if not colegio.es_demo:
            raise NoEsDemo(subdominio)
        # Un solo reinicio a la vez por colegio (dos clics seguidos en "Reiniciar").
        db.execute(text("SELECT pg_advisory_xact_lock(7, :c)"), {"c": colegio.id})
        borrar_datos(db, colegio)
        db.flush()
    res = sembrar(db, colegio, alumnos_por_seccion)
    db.commit()
    return res
