"""Carga masiva del padrón desde Excel: hoja "Alumnos" (con hasta dos
apoderados por fila) y hoja "Personal".

Se usa en dos pasos con el mismo archivo: `analizar` arma el plan y la lista
de errores sin tocar la base (vista previa); `aplicar` ejecuta ese plan, solo
si no hubo ningún error. La confirmación vuelve a analizar el archivo, así lo
que se aplica es lo que la base tiene en ese momento.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import codigos, familias, pensiones, validacion
from app.models import (Alumno, AlumnoApoderado, AnioEscolar, Apoderado, Grado, Matricula, Nivel, Rol, Seccion,
                        Usuario)
from app.proteccion import generar_clave_temporal
from app.seguridad import hashear_clave

MAX_BYTES = 5 * 1024 * 1024
MAX_FILAS = 3000
MAX_ERRORES = 300
APODERADOS_POR_FILA = 2

# Encabezados de la plantilla. Se reconocen sin importar mayúsculas, tildes ni el orden.
COL_ALUMNOS = {
    "tipo_documento": "Tipo doc", "numero_documento": "N° documento", "apellidos": "Apellidos",
    "nombres": "Nombres", "fecha_nacimiento": "Fecha de nacimiento", "nivel": "Nivel", "grado": "Grado",
    "seccion": "Sección",
}
COL_APODERADO = {
    "tipo_documento": "tipo doc", "numero_documento": "documento", "apellidos": "apellidos",
    "nombres": "nombres", "parentesco": "parentesco", "celular": "celular", "correo": "correo",
    "responsable": "responsable de pago",
}
SI_NO = {"si": True, "s": True, "x": True, "no": False, "n": False, "": False}
COL_PERSONAL = {
    "tipo_documento": "Tipo doc", "numero_documento": "N° documento", "apellidos": "Apellidos",
    "nombres": "Nombres", "rol": "Rol", "celular": "Celular", "correo": "Correo",
}
OBLIGATORIAS_ALUMNOS = ("numero_documento", "apellidos", "nombres", "nivel", "grado", "seccion")
OBLIGATORIAS_PERSONAL = ("numero_documento", "apellidos", "nombres", "rol")


def _cab(texto) -> str:
    t = validacion.clave_texto(texto or "")
    for basura in ("n°", "nº", "n.°", "°", "º", ".", ":"):
        t = t.replace(basura, "")
    return " ".join(t.split())


def _clave_grado(texto) -> str:
    """'3°', '3 ', 'tercero' no se igualan, pero '3°' y '3' sí."""
    return _cab(texto)


def _columnas_alumnos() -> dict[str, str]:
    cols = {_cab(v): k for k, v in COL_ALUMNOS.items()}
    for n in range(1, APODERADOS_POR_FILA + 1):
        for k, v in COL_APODERADO.items():
            cols[_cab(f"Apoderado {n} {v}")] = f"ap{n}_{k}"
    return cols


ALIAS = {"dni": "numero_documento", "documento": "numero_documento", "numero de documento": "numero_documento",
         "tipo de documento": "tipo_documento", "tipo documento": "tipo_documento",
         "fecha nacimiento": "fecha_nacimiento", "seccion": "seccion"}


class ArchivoInvalido(Exception):
    pass


@dataclass
class Error:
    hoja: str
    fila: int | None
    columna: str | None
    mensaje: str


@dataclass
class DatosApo:
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    celular: str | None
    correo: str | None
    parentesco: str
    fila: int
    responsable: bool = False


@dataclass
class FilaAlumno:
    fila: int
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    fecha_nacimiento: date | None
    seccion: Seccion
    apoderados: list[DatosApo]


@dataclass
class FilaPersonal:
    fila: int
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    rol: Rol
    celular: str | None
    correo: str | None


@dataclass
class Analisis:
    anio: AnioEscolar
    errores: list[Error] = field(default_factory=list)
    total_errores: int = 0
    alumnos: list[FilaAlumno] = field(default_factory=list)
    personal: list[FilaPersonal] = field(default_factory=list)
    resumen: dict[str, int] = field(default_factory=dict)

    def error(self, hoja: str, fila: int | None, columna: str | None, mensaje: str) -> None:
        self.total_errores += 1
        if len(self.errores) < MAX_ERRORES:
            self.errores.append(Error(hoja, fila, columna, mensaje))


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _numero_doc(tipo: str, valor) -> str:
    # Excel guarda los DNI como número y se come los ceros de adelante (01234567 -> 1234567).
    if tipo == "DNI" and isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return str(int(valor)).zfill(8)
    return _texto(valor)


def _fecha(valor) -> date | None:
    if valor is None or _texto(valor) == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    t = _texto(valor)
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            pass
    raise ValueError("Fecha no válida (usa dd/mm/aaaa)")


def _leer_hoja(hoja, columnas: dict[str, str], obligatorias: tuple[str, ...], nombre: str,
               a: Analisis) -> list[tuple[int, dict]]:
    filas = hoja.iter_rows(values_only=True)
    try:
        encabezados = next(filas)
    except StopIteration:
        return []
    mapa: dict[int, str] = {}
    for i, h in enumerate(encabezados):
        clave = columnas.get(_cab(h)) or ALIAS.get(_cab(h))
        if clave and clave in columnas.values() and clave not in mapa.values():
            mapa[i] = clave
    faltan = [c for c in obligatorias if c not in mapa.values()]
    if faltan:
        nombres = {v: k for k, v in columnas.items()}
        a.error(nombre, 1, None, "Faltan columnas: " + ", ".join(
            (COL_ALUMNOS | COL_PERSONAL).get(c, nombres.get(c, c)) for c in faltan))
        return []
    salida = []
    for n, valores in enumerate(filas, start=2):
        if all(_texto(v) == "" for v in valores):
            continue
        if len(salida) >= MAX_FILAS:
            a.error(nombre, n, None, f"La hoja pasa de {MAX_FILAS} filas; divídela en varios archivos")
            break
        salida.append((n, {clave: valores[i] if i < len(valores) else None for i, clave in mapa.items()}))
    return salida


def _documento(datos: dict, prefijo: str, permitidos: tuple[str, ...], hoja: str, n: int, a: Analisis,
               etiqueta: str) -> tuple[str, str] | None:
    try:
        tipo = validacion.tipo_documento(_texto(datos.get(f"{prefijo}tipo_documento")) or None, permitidos)
    except ValueError as e:
        a.error(hoja, n, f"{etiqueta}tipo doc", str(e))
        return None
    try:
        return tipo, validacion.documento(tipo, _numero_doc(tipo, datos.get(f"{prefijo}numero_documento")))
    except ValueError as e:
        a.error(hoja, n, f"{etiqueta}documento", str(e))
        return None


def _campo(fn, valor, hoja: str, n: int, columna: str, a: Analisis):
    try:
        return fn(valor), True
    except ValueError as e:
        a.error(hoja, n, columna, str(e))
        return None, False


def analizar(db: Session, colegio_id: int, anio: AnioEscolar, contenido: bytes,
             puede_personal: bool, es_director: bool) -> Analisis:
    a = Analisis(anio=anio)
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido("El archivo pesa más de 5 MB")
    try:
        libro = load_workbook(BytesIO(contenido), read_only=True, data_only=True)
    except (BadZipFile, KeyError, OSError, ValueError):
        raise ArchivoInvalido("No es un archivo de Excel (.xlsx) válido") from None
    hojas = {_cab(h): h for h in libro.sheetnames}
    if "alumnos" not in hojas and "personal" not in hojas:
        raise ArchivoInvalido('El archivo debe tener una hoja "Alumnos" o una hoja "Personal"')

    if "alumnos" in hojas:
        filas = _leer_hoja(libro[hojas["alumnos"]], _columnas_alumnos(), OBLIGATORIAS_ALUMNOS, "Alumnos", a)
        _analizar_alumnos(db, colegio_id, anio, filas, a)
    if "personal" in hojas:
        cols = {_cab(v): k for k, v in COL_PERSONAL.items()}
        filas = _leer_hoja(libro[hojas["personal"]], cols, OBLIGATORIAS_PERSONAL, "Personal", a)
        if filas and not puede_personal:
            a.error("Personal", None, None, "No tienes permiso para cargar personal")
        else:
            _analizar_personal(db, colegio_id, filas, es_director, a)
    libro.close()
    return a


def _analizar_alumnos(db: Session, cid: int, anio: AnioEscolar, filas: list[tuple[int, dict]],
                      a: Analisis) -> None:
    H = "Alumnos"
    secciones = {
        (_cab(n), _clave_grado(g), _cab(s.nombre)): s
        for s, g, n in db.execute(
            select(Seccion, Grado.nombre, Nivel.nombre)
            .join(Grado, (Grado.colegio_id == Seccion.colegio_id) & (Grado.id == Seccion.grado_id))
            .join(Nivel, (Nivel.colegio_id == Grado.colegio_id) & (Nivel.id == Grado.nivel_id))
            .where(Seccion.colegio_id == cid, Seccion.anio_id == anio.id))
    }
    alumnos = {(x.tipo_documento, x.numero_documento): x
               for x in db.scalars(select(Alumno).where(Alumno.colegio_id == cid))}
    matriculas = dict(db.execute(select(Matricula.alumno_id, Matricula.seccion_id)
                                 .where(Matricula.colegio_id == cid, Matricula.anio_id == anio.id)).all())
    apoderados = {(x.tipo_documento, x.numero_documento): x
                  for x in db.scalars(select(Apoderado).where(Apoderado.colegio_id == cid))}
    vinculos = set(db.execute(select(AlumnoApoderado.alumno_id, AlumnoApoderado.apoderado_id)
                              .where(AlumnoApoderado.colegio_id == cid)).all())

    vistos: dict[tuple[str, str], int] = {}
    apos_archivo: dict[tuple[str, str], DatosApo] = {}
    r = dict.fromkeys(("alumnos_nuevos", "alumnos_actualizados", "matriculas_nuevas", "cambios_seccion",
                       "apoderados_nuevos", "apoderados_actualizados", "vinculos_nuevos"), 0)

    for n, d in filas:
        ok = True
        doc = _documento(d, "", validacion.TIPOS_DOCUMENTO, H, n, a, "")
        ok &= doc is not None
        if doc and doc in vistos:
            a.error(H, n, "N° documento", f"El alumno ya aparece en la fila {vistos[doc]}")
            ok = False
        elif doc:
            vistos[doc] = n
        nombres, v1 = _campo(validacion.nombre, d.get("nombres"), H, n, "Nombres", a)
        apellidos, v2 = _campo(validacion.nombre, d.get("apellidos"), H, n, "Apellidos", a)
        fecha, v3 = _campo(_fecha, d.get("fecha_nacimiento"), H, n, "Fecha de nacimiento", a)
        ok &= v1 and v2 and v3
        clave_sec = (_cab(_texto(d.get("nivel"))), _clave_grado(_texto(d.get("grado"))),
                     _cab(_texto(d.get("seccion"))))
        seccion = secciones.get(clave_sec)
        if seccion is None:
            a.error(H, n, "Sección", f"No existe la sección {_texto(d.get('nivel'))} {_texto(d.get('grado'))} "
                                     f"{_texto(d.get('seccion'))} en el año {anio.anio}")
            ok = False

        apos: list[DatosApo] = []
        for k in range(1, APODERADOS_POR_FILA + 1):
            p = f"ap{k}_"
            et = f"Apoderado {k} "
            if all(_texto(d.get(p + c)) == "" for c in COL_APODERADO):
                continue
            adoc = _documento(d, p, validacion.TIPOS_DOCUMENTO, H, n, a, et)
            anombres, w1 = _campo(validacion.nombre, d.get(p + "nombres"), H, n, et + "nombres", a)
            aapellidos, w2 = _campo(validacion.nombre, d.get(p + "apellidos"), H, n, et + "apellidos", a)
            cel, w3 = _campo(validacion.celular, _texto(d.get(p + "celular")), H, n, et + "celular", a)
            mail, w4 = _campo(validacion.correo, _texto(d.get(p + "correo")), H, n, et + "correo", a)
            parentesco = " ".join(_texto(d.get(p + "parentesco")).split())[:30] or "Apoderado"
            responsable = SI_NO.get(_cab(_texto(d.get(p + "responsable"))))
            w5 = responsable is not None
            if not w5:
                a.error(H, n, et + "responsable de pago", "Escribe Sí o No (o déjalo vacío)")
            elif responsable and any(x.responsable for x in apos):
                a.error(H, n, et + "responsable de pago", "Solo un apoderado por alumno es responsable de pago")
                w5 = False
            if not (adoc and w1 and w2 and w3 and w4 and w5):
                ok = False
                continue
            if adoc == doc:
                a.error(H, n, et + "documento", "El apoderado no puede ser el mismo alumno")
                ok = False
                continue
            previo = apos_archivo.get(adoc)
            if previo and (previo.nombres, previo.apellidos) != (anombres, aapellidos):
                a.error(H, n, et + "nombres", f"El apoderado {adoc[1]} aparece con otro nombre en la fila "
                                              f"{previo.fila}")
                ok = False
                continue
            datos = DatosApo(adoc[0], adoc[1], anombres, aapellidos, cel or (previo.celular if previo else None),
                             mail or (previo.correo if previo else None), parentesco, n, responsable)
            apos_archivo[adoc] = datos
            apos.append(datos)

        if not ok:
            continue
        a.alumnos.append(FilaAlumno(n, doc[0], doc[1], nombres, apellidos, fecha, seccion, apos))
        existente = alumnos.get(doc)
        if existente is None:
            r["alumnos_nuevos"] += 1
            r["matriculas_nuevas"] += 1
        else:
            if (existente.nombres, existente.apellidos, existente.fecha_nacimiento) != (
                    nombres, apellidos, fecha or existente.fecha_nacimiento):
                r["alumnos_actualizados"] += 1
            actual = matriculas.get(existente.id)
            if actual is None:
                r["matriculas_nuevas"] += 1
            elif actual != seccion.id:
                r["cambios_seccion"] += 1
        for ap in apos:
            previo_db = apoderados.get((ap.tipo_documento, ap.numero_documento))
            if previo_db is None or existente is None or (existente.id, previo_db.id) not in vinculos:
                r["vinculos_nuevos"] += 1

    for clave, ap in apos_archivo.items():
        previo_db = apoderados.get(clave)
        if previo_db is None:
            r["apoderados_nuevos"] += 1
        elif (previo_db.nombres, previo_db.apellidos, previo_db.celular, previo_db.correo) != (
                ap.nombres, ap.apellidos, ap.celular or previo_db.celular, ap.correo or previo_db.correo):
            r["apoderados_actualizados"] += 1
    a.resumen.update(r)


def _analizar_personal(db: Session, cid: int, filas: list[tuple[int, dict]], es_director: bool,
                       a: Analisis) -> None:
    H = "Personal"
    roles = {_cab(r.nombre): r for r in db.scalars(select(Rol).where(Rol.colegio_id == cid))}
    existentes = {(u.tipo_documento, u.numero_documento): u
                  for u in db.scalars(select(Usuario).where(Usuario.colegio_id == cid))}
    usuarios = {u.usuario for u in existentes.values()}
    vistos: dict[tuple[str, str], int] = {}
    nuevos = actualizados = 0

    for n, d in filas:
        doc = _documento(d, "", validacion.TIPOS_DOCUMENTO_PERSONAL, H, n, a, "")
        ok = doc is not None
        if doc and doc in vistos:
            a.error(H, n, "N° documento", f"La persona ya aparece en la fila {vistos[doc]}")
            ok = False
        elif doc:
            vistos[doc] = n
        nombres, v1 = _campo(validacion.nombre, d.get("nombres"), H, n, "Nombres", a)
        apellidos, v2 = _campo(validacion.nombre, d.get("apellidos"), H, n, "Apellidos", a)
        cel, v3 = _campo(validacion.celular, _texto(d.get("celular")), H, n, "Celular", a)
        mail, v4 = _campo(validacion.correo, _texto(d.get("correo")), H, n, "Correo", a)
        ok &= v1 and v2 and v3 and v4
        rol = roles.get(_cab(_texto(d.get("rol"))))
        if rol is None:
            a.error(H, n, "Rol", f"No existe el rol \"{_texto(d.get('rol'))}\"; créalo primero en Roles")
            ok = False
        elif rol.es_director and not es_director:
            a.error(H, n, "Rol", "Solo el director asigna el rol de director")
            ok = False
        existente = existentes.get(doc) if doc else None
        if existente and rol and existente.rol.es_director and not rol.es_director:
            a.error(H, n, "Rol", "El rol de un director no se cambia desde Excel")
            ok = False
        if doc and existente is None and doc[1] in usuarios:
            a.error(H, n, "N° documento", "Ya hay otra persona con ese usuario")
            ok = False
        if not ok:
            continue
        a.personal.append(FilaPersonal(n, doc[0], doc[1], nombres, apellidos, rol, cel, mail))
        if existente is None:
            nuevos += 1
        elif (existente.nombres, existente.apellidos, existente.rol_id, existente.celular, existente.correo) != (
                nombres, apellidos, rol.id, cel or existente.celular, mail or existente.correo):
            actualizados += 1
    a.resumen.update(personal_nuevo=nuevos, personal_actualizado=actualizados)


@dataclass
class Credencial:
    nombres: str
    apellidos: str
    usuario: str
    clave_temporal: str


def aplicar(db: Session, colegio_id: int, a: Analisis, usuario_id: int | None = None) -> list[Credencial]:
    """Ejecuta el plan. Quien llama hace el commit (todo o nada). `usuario_id`: quien cargó
    el archivo, para el registro de cambios de contacto de los apoderados."""
    assert a.total_errores == 0
    cid = colegio_id
    alumnos = {(x.tipo_documento, x.numero_documento): x
               for x in db.scalars(select(Alumno).where(Alumno.colegio_id == cid))}
    apoderados = {(x.tipo_documento, x.numero_documento): x
                  for x in db.scalars(select(Apoderado).where(Apoderado.colegio_id == cid))}
    matriculas = {m.alumno_id: m for m in db.scalars(
        select(Matricula).where(Matricula.colegio_id == cid, Matricula.anio_id == a.anio.id))}
    vinculos = {(v.alumno_id, v.apoderado_id): v for v in db.scalars(
        select(AlumnoApoderado).where(AlumnoApoderado.colegio_id == cid))}
    reservados: set[str] = set()

    for f in a.alumnos:
        al = alumnos.get((f.tipo_documento, f.numero_documento))
        if al is None:
            al = Alumno(colegio_id=cid, tipo_documento=f.tipo_documento, numero_documento=f.numero_documento,
                        codigo=codigos.generar(db, cid, reservados))
            db.add(al)
            alumnos[(f.tipo_documento, f.numero_documento)] = al
        al.nombres, al.apellidos = f.nombres, f.apellidos
        al.fecha_nacimiento = f.fecha_nacimiento or al.fecha_nacimiento
        db.flush()
        m = matriculas.get(al.id)
        if m is None:
            m = Matricula(colegio_id=cid, anio_id=a.anio.id, alumno_id=al.id, seccion_id=f.seccion.id)
            db.add(m)
            matriculas[al.id] = m
            pensiones.al_matricular(db, cid, al.id, a.anio.id)
        elif m.seccion_id != f.seccion.id:
            m.seccion_id = f.seccion.id
            pensiones.al_matricular(db, cid, al.id, a.anio.id)
        for d in f.apoderados:
            ap = apoderados.get((d.tipo_documento, d.numero_documento))
            if ap is None:
                ap = Apoderado(colegio_id=cid, tipo_documento=d.tipo_documento, numero_documento=d.numero_documento)
                db.add(ap)
                apoderados[(d.tipo_documento, d.numero_documento)] = ap
            ap.nombres, ap.apellidos = d.nombres, d.apellidos
            familias.cambiar_contacto(db, ap, d.celular, d.correo, "excel", usuario_id)
            db.flush()
            v = vinculos.get((al.id, ap.id))
            if v is None:
                v = AlumnoApoderado(colegio_id=cid, alumno_id=al.id, apoderado_id=ap.id)
                db.add(v)
                vinculos[(al.id, ap.id)] = v
            v.parentesco = d.parentesco
            if d.responsable:  # vacío o "No" no cambia al responsable que ya tenga
                pensiones.marcar_responsable(db, cid, al.id, ap.id)

    credenciales = []
    existentes = {(u.tipo_documento, u.numero_documento): u
                  for u in db.scalars(select(Usuario).where(Usuario.colegio_id == cid))}
    for f in a.personal:
        u = existentes.get((f.tipo_documento, f.numero_documento))
        if u is None:
            clave = generar_clave_temporal()
            u = Usuario(colegio_id=cid, tipo_documento=f.tipo_documento, numero_documento=f.numero_documento,
                        usuario=f.numero_documento, clave_hash=hashear_clave(clave), debe_cambiar_clave=True)
            db.add(u)
            credenciales.append(Credencial(f.nombres, f.apellidos, f.numero_documento, clave))
        u.nombres, u.apellidos, u.rol_id = f.nombres, f.apellidos, f.rol.id
        u.celular, u.correo = f.celular or u.celular, f.correo or u.correo
    db.flush()
    return credenciales


def plantilla(secciones: list[tuple[str, str, str]], roles: list[str]) -> bytes:
    """Plantilla con las dos hojas, y como referencia las secciones y roles que ya existen."""
    libro = Workbook()
    negrita = Font(bold=True, color="FFFFFF")
    fondo = PatternFill("solid", fgColor="1F4E79")

    def hoja(titulo: str, encabezados: list[str], ws=None):
        ws = ws or libro.create_sheet(titulo)
        ws.title = titulo
        ws.append(encabezados)
        for celda in ws[1]:
            celda.font, celda.fill = negrita, fondo
            ws.column_dimensions[celda.column_letter].width = max(14, len(str(celda.value)) + 4)
        ws.freeze_panes = "A2"
        return ws

    cab_alumnos = list(COL_ALUMNOS.values())
    for n in range(1, APODERADOS_POR_FILA + 1):
        cab_alumnos += [f"Apoderado {n} {v}" for v in COL_APODERADO.values()]
    al = hoja("Alumnos", cab_alumnos, libro.active)
    pe = hoja("Personal", list(COL_PERSONAL.values()))

    tipos = DataValidation(type="list", formula1='"DNI,CE,PAS,OTRO"', allow_blank=True)
    al.add_data_validation(tipos)
    tipos.add("A2:A3001")
    for n in range(APODERADOS_POR_FILA):
        col = al.cell(row=1, column=len(COL_ALUMNOS) + 1 + n * len(COL_APODERADO)).column_letter
        tipos.add(f"{col}2:{col}3001")
    tipos_pe = DataValidation(type="list", formula1='"DNI,CE"', allow_blank=True)
    pe.add_data_validation(tipos_pe)
    tipos_pe.add("A2:A3001")
    # Documento y celular como texto, para que Excel no se coma los ceros. Se aplica a la
    # columna entera (no celda por celda): así la hoja sigue terminando en la fila 1 y
    # lo que se agregue al final empieza en la fila 2.
    for ws in (al, pe):
        for celda in ws[1]:
            if any(p in str(celda.value).lower() for p in ("documento", "celular")):
                ws.column_dimensions[celda.column_letter].number_format = "@"

    ref = hoja("Secciones (referencia)", ["Nivel", "Grado", "Sección"])
    for fila in secciones:
        ref.append(list(fila))
    rr = hoja("Roles (referencia)", ["Rol"])
    for r in roles:
        rr.append([r])
    ins = libro.create_sheet("Instrucciones")
    for linea in (
        "Llena la hoja Alumnos, la hoja Personal o ambas. No cambies los encabezados.",
        "Nivel, Grado y Sección deben existir ya en el año escolar (mira la hoja Secciones).",
        "Tipo doc: DNI, CE (carné de extranjería), PAS (pasaporte) u OTRO. Si se deja vacío, se toma DNI.",
        "Celular: 9 dígitos que empiezan con 9. Fecha de nacimiento: dd/mm/aaaa.",
        "Responsable de pago: Sí en el apoderado que ve la deuda y recibe los avisos de cobro (uno por alumno). "
        "Si nadie tiene Sí, se toma el primero.",
        "Si un alumno o persona ya existe (mismo documento), se actualizan sus datos.",
        "Personal: el Rol debe existir (mira la hoja Roles). El usuario será su número de documento.",
        "Antes de guardar se muestra una vista previa con los errores: no se guarda nada hasta que no haya ninguno.",
    ):
        ins.append([linea])
    ins.column_dimensions["A"].width = 110

    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
