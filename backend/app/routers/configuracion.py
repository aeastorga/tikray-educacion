"""Configuración del administrador: perfil del colegio, módulos, avisos a los padres, plantillas de comunicados,
categorías de incidencias, comprobantes electrónicos e historial de actividad.

Todo con el colegio del token. Ver: permiso "configuracion" ver; cambiar: "configuracion" editar. El
historial y los comprobantes electrónicos son solo del administrador (y de Tikray Labs en su panel).
"""

from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import configuracion, facturacion
from app.comun import guardar, obtener
from app.db import get_db
from app.deps import Sesion, puede, requerir_permiso, solo_administrador, usuario_actual
from app.fechas import LIMA
from app.paginacion import Pagina, contar, pagina, recortar
from app.models import CategoriaIncidencia, Colegio, EntradaCuaderno, PlantillaComunicado, RegistroActividad, Usuario
from app.models.colegio import CONTRATABLES, TIPOS_AVISO
from app.models.facturacion import PATRON_SERIE_BOLETA, PATRON_SERIE_FACTURA
from app.modulos import MODULOS

router = APIRouter(prefix="/configuracion", tags=["configuracion"])
ver = requerir_permiso("configuracion")
editar = requerir_permiso("configuracion", "editar")

TELEFONO = r"^[0-9+()\- ]{6,20}$"
CORREO = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# --- Perfil del colegio (lo usa también el panel de Tikray Labs) ------------------------------

class Perfil(BaseModel):
    tipo_gestion: Literal["particular", "estatal"] = "particular"
    ugel: str | None = Field(default=None, max_length=120)
    codigo_modular: str | None = Field(default=None, pattern=r"^\d{7}$")
    direccion: str | None = Field(default=None, max_length=250)
    telefono: str | None = Field(default=None, pattern=TELEFONO)
    correo_contacto: str | None = Field(default=None, max_length=254, pattern=CORREO)

    @field_validator("ugel", "codigo_modular", "direccion", "telefono", "correo_contacto", mode="before")
    @classmethod
    def _vacio_es_nada(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


CAMPOS_PERFIL = tuple(Perfil.model_fields)


def perfil_de(c: Colegio) -> dict:
    return {campo: getattr(c, campo) for campo in CAMPOS_PERFIL}


def aplicar_perfil(c: Colegio, d: Perfil) -> list[str]:
    """Cambia el perfil y devuelve qué campos cambiaron (para el historial, sin los valores)."""
    cambios = []
    for campo, valor in d.model_dump().items():
        if campo == "correo_contacto" and valor:
            valor = valor.lower()
        if getattr(c, campo) != valor:
            setattr(c, campo, valor)
            cambios.append(campo)
    return cambios


NOMBRE_CAMPO = {"tipo_gestion": "tipo de gestión", "ugel": "UGEL", "codigo_modular": "código modular",
                "direccion": "dirección", "telefono": "teléfono", "correo_contacto": "correo"}


@router.get("/perfil")
def ver_perfil(s: Sesion = Depends(ver)) -> dict:
    return perfil_de(s.colegio)


@router.put("/perfil")
def cambiar_perfil(d: Perfil, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cambios = aplicar_perfil(s.colegio, d)
    if cambios:
        configuracion.registrar(db, s.colegio.id, s.usuario, "editar", "configuracion", "perfil", s.colegio.id,
                                "Perfil del colegio: " + ", ".join(NOMBRE_CAMPO[c] for c in cambios))
    guardar(db)
    return perfil_de(s.colegio)


# --- Módulos -------------------------------------------------------------------------------

def modulos_de(c: Colegio) -> list[dict]:
    return [{"clave": m, "nombre": MODULOS[m], "contratado": m in (c.modulos_contratados or []),
             "activo": c.modulo_activo(m)} for m in CONTRATABLES]


class ModulosIn(BaseModel):
    activos: list[str] = Field(max_length=len(CONTRATABLES))


@router.get("/modulos")
def ver_modulos(s: Sesion = Depends(ver)) -> list[dict]:
    return modulos_de(s.colegio)


@router.put("/modulos")
def cambiar_modulos(d: ModulosIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> list[dict]:
    """El administrador prende o apaga solo dentro de lo contratado."""
    c = s.colegio
    activos = set(d.activos)
    if activos - set(CONTRATABLES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Módulo desconocido")
    no_contratados = activos - set(c.modulos_contratados or [])
    if no_contratados:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"No está contratado: {', '.join(MODULOS[m] for m in sorted(no_contratados))}")
    antes = {m for m in CONTRATABLES if c.modulo_activo(m)}
    c.modulos_apagados = sorted(set(c.modulos_contratados or []) - activos)
    despues = {m for m in CONTRATABLES if c.modulo_activo(m)}
    partes = [f"prendió {MODULOS[m]}" for m in sorted(despues - antes)] + \
             [f"apagó {MODULOS[m]}" for m in sorted(antes - despues)]
    if partes:
        configuracion.registrar(db, c.id, s.usuario, "editar", "configuracion", "modulos", c.id,
                                "Módulos: " + "; ".join(partes))
    guardar(db)
    return modulos_de(c)


# --- Avisos a los padres -------------------------------------------------------------------

class AvisosIn(BaseModel):
    tipos: dict[Literal["ingreso", "tardanza", "falta", "salida", "cuaderno", "cobro"], bool]
    silencio_desde: time
    silencio_hasta: time


def avisos_de(c: Colegio) -> dict:
    tipos = {t: bool((c.avisos_tipos or {}).get(t, True)) for t in TIPOS_AVISO}
    return {"tipos": tipos, "silencio_desde": c.silencio_desde.strftime("%H:%M"),
            "silencio_hasta": c.silencio_hasta.strftime("%H:%M")}


@router.get("/avisos")
def ver_avisos(s: Sesion = Depends(ver)) -> dict:
    return avisos_de(s.colegio)


@router.put("/avisos")
def cambiar_avisos(d: AvisosIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    c = s.colegio
    antes = avisos_de(c)
    c.avisos_tipos = {t: d.tipos.get(t, antes["tipos"][t]) for t in TIPOS_AVISO}
    c.silencio_desde = d.silencio_desde.replace(second=0, microsecond=0, tzinfo=None)
    c.silencio_hasta = d.silencio_hasta.replace(second=0, microsecond=0, tzinfo=None)
    despues = avisos_de(c)
    partes = [f"{'activó' if despues['tipos'][t] else 'apagó'} {t}" for t in TIPOS_AVISO
              if antes["tipos"][t] != despues["tipos"][t]]
    if (antes["silencio_desde"], antes["silencio_hasta"]) != (despues["silencio_desde"], despues["silencio_hasta"]):
        partes.append(f"sin molestar de {despues['silencio_desde']} a {despues['silencio_hasta']}")
    if partes:
        configuracion.registrar(db, c.id, s.usuario, "editar", "configuracion", "avisos", c.id,
                                "Avisos a los padres: " + "; ".join(partes))
    guardar(db)
    return despues


# --- Plantillas de comunicados ------------------------------------------------------------

class PlantillaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    titulo: str = Field(min_length=1, max_length=200)
    cuerpo: str = Field(default="", max_length=10000)


def _plantilla(p: PlantillaComunicado) -> dict:
    return {"id": p.id, "nombre": p.nombre, "titulo": p.titulo, "cuerpo": p.cuerpo}


@router.get("/plantillas")
def plantillas(s: Sesion = Depends(usuario_actual), db: Session = Depends(get_db)) -> list[dict]:
    """Las ve quien configura y quien escribe en el cuaderno."""
    if not (puede(s, "configuracion") or puede(s, "cuaderno", "editar")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso para este módulo")
    return [_plantilla(p) for p in db.scalars(select(PlantillaComunicado).where(
        PlantillaComunicado.colegio_id == s.colegio.id).order_by(PlantillaComunicado.nombre))]


@router.post("/plantillas", status_code=201)
def crear_plantilla(d: PlantillaIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    p = PlantillaComunicado(colegio_id=s.colegio.id, nombre=d.nombre.strip(), titulo=d.titulo.strip(),
                            cuerpo=d.cuerpo.strip())
    db.add(p)
    guardar(db, repetido="Ya hay una plantilla con ese nombre", solo_flush=True)
    configuracion.registrar(db, s.colegio.id, s.usuario, "crear", "configuracion", "plantilla", p.id,
                            f"Plantilla «{p.nombre}»")
    guardar(db)
    return _plantilla(p)


@router.put("/plantillas/{plantilla_id}")
def editar_plantilla(plantilla_id: int, d: PlantillaIn, s: Sesion = Depends(editar),
                     db: Session = Depends(get_db)) -> dict:
    p = obtener(db, PlantillaComunicado, s.colegio.id, plantilla_id, "Plantilla")
    p.nombre, p.titulo, p.cuerpo = d.nombre.strip(), d.titulo.strip(), d.cuerpo.strip()
    configuracion.registrar(db, s.colegio.id, s.usuario, "editar", "configuracion", "plantilla", p.id,
                            f"Plantilla «{p.nombre}»")
    guardar(db, repetido="Ya hay una plantilla con ese nombre")
    return _plantilla(p)


@router.delete("/plantillas/{plantilla_id}", status_code=204)
def borrar_plantilla(plantilla_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    p = obtener(db, PlantillaComunicado, s.colegio.id, plantilla_id, "Plantilla")
    configuracion.registrar(db, s.colegio.id, s.usuario, "anular", "configuracion", "plantilla", p.id,
                            f"Borró la plantilla «{p.nombre}»")
    db.delete(p)
    guardar(db)


# --- Categorías de incidencias ------------------------------------------------------------

class CategoriaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    tipo: Literal["merito", "mejora"]
    activa: bool = True


def _categoria(c: CategoriaIncidencia, usos: int = 0) -> dict:
    return {"id": c.id, "nombre": c.nombre, "tipo": c.tipo, "activa": c.activa, "usos": usos}


@router.get("/categorias")
def categorias(s: Sesion = Depends(usuario_actual), db: Session = Depends(get_db)) -> list[dict]:
    """Para elegirla al registrar una incidencia (cualquiera del personal) y para configurarlas."""
    cid = s.colegio.id
    usos = dict(db.execute(select(EntradaCuaderno.categoria_id, func.count()).where(
        EntradaCuaderno.colegio_id == cid, EntradaCuaderno.categoria_id.is_not(None))
        .group_by(EntradaCuaderno.categoria_id)).all())
    return [_categoria(c, usos.get(c.id, 0)) for c in db.scalars(select(CategoriaIncidencia).where(
        CategoriaIncidencia.colegio_id == cid).order_by(CategoriaIncidencia.tipo, CategoriaIncidencia.orden,
                                                         CategoriaIncidencia.nombre))]


TIPO_CATEGORIA = {"merito": "mérito", "mejora": "a mejorar"}


@router.post("/categorias", status_code=201)
def crear_categoria(d: CategoriaIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    orden = (db.scalar(select(func.max(CategoriaIncidencia.orden)).where(CategoriaIncidencia.colegio_id == cid)) or 0)
    c = CategoriaIncidencia(colegio_id=cid, nombre=d.nombre.strip(), tipo=d.tipo, activa=d.activa, orden=orden + 1)
    db.add(c)
    guardar(db, repetido="Ya hay una categoría con ese nombre", solo_flush=True)
    configuracion.registrar(db, cid, s.usuario, "crear", "configuracion", "categoria", c.id,
                            f"Categoría «{c.nombre}» ({TIPO_CATEGORIA[c.tipo]})")
    guardar(db)
    return _categoria(c)


@router.put("/categorias/{categoria_id}")
def editar_categoria(categoria_id: int, d: CategoriaIn, s: Sesion = Depends(editar),
                     db: Session = Depends(get_db)) -> dict:
    c = obtener(db, CategoriaIncidencia, s.colegio.id, categoria_id, "Categoría")
    c.nombre, c.tipo, c.activa = d.nombre.strip(), d.tipo, d.activa
    configuracion.registrar(db, s.colegio.id, s.usuario, "editar", "configuracion", "categoria", c.id,
                            f"Categoría «{c.nombre}» ({TIPO_CATEGORIA[c.tipo]}{'' if c.activa else ', desactivada'})")
    guardar(db, repetido="Ya hay una categoría con ese nombre")
    return _categoria(c)


@router.delete("/categorias/{categoria_id}", status_code=204)
def borrar_categoria(categoria_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    """Solo si ninguna incidencia la usa; si no, se desactiva (así lo ya registrado conserva su categoría)."""
    cid = s.colegio.id
    c = obtener(db, CategoriaIncidencia, cid, categoria_id, "Categoría")
    if db.scalar(select(EntradaCuaderno.id).where(EntradaCuaderno.colegio_id == cid,
                                                  EntradaCuaderno.categoria_id == c.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Hay incidencias con esta categoría: desactívala en vez de borrarla")
    configuracion.registrar(db, cid, s.usuario, "anular", "configuracion", "categoria", c.id,
                            f"Borró la categoría «{c.nombre}»")
    db.delete(c)
    guardar(db)


# --- Comprobantes electrónicos (solo el administrador; lo usa también el panel de Tikray Labs) ----------

class FacturacionIn(BaseModel):
    emite: bool = False
    ruc: str | None = None
    razon_social: str | None = Field(default=None, max_length=200)
    serie_boleta: str = Field(default="B001", pattern=PATRON_SERIE_BOLETA)
    serie_factura: str = Field(default="F001", pattern=PATRON_SERIE_FACTURA)
    proveedor: str = "ninguno"
    # Vacío: se queda el que ya estaba. Nunca se devuelve.
    token: str | None = Field(default=None, max_length=2000)

    @field_validator("ruc", "razon_social", "token", mode="before")
    @classmethod
    def _vacio_es_nada(cls, v):
        return (" ".join(v.split()) or None) if isinstance(v, str) else v

    @field_validator("serie_boleta", "serie_factura", mode="before")
    @classmethod
    def _mayusculas(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("proveedor")
    @classmethod
    def _proveedor(cls, v: str) -> str:
        if v not in facturacion.PROVEEDORES:
            raise ValueError("Proveedor desconocido")
        return v


def aplicar_facturacion(db: Session, colegio_id: int, d: FacturacionIn, quien) -> dict:
    """Guarda la configuración y su línea del historial (sin el token) y hace commit."""
    from app.models import ConfigFacturacion

    cfg = db.get(ConfigFacturacion, colegio_id) or ConfigFacturacion(colegio_id=colegio_id)
    if d.ruc is not None and not facturacion.ruc_valido(d.ruc):  # con su mensaje en pantalla
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, facturacion.RUC_INVALIDO)
    sin_clave = "Falta FACTURACION_CLAVE en el servidor: la facturación no se puede activar"
    if d.token and not facturacion.hay_clave():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, sin_clave)
    if d.emite:
        if not facturacion.hay_clave():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, sin_clave)
        if not d.ruc or not d.razon_social:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Para emitir, escribe el RUC y la razón social")
        if d.proveedor != "ninguno" and not (d.token or cfg.token_cifrado):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Para emitir, escribe el token del proveedor")
    cfg.emite, cfg.ruc, cfg.razon_social = d.emite, d.ruc, d.razon_social
    cfg.serie_boleta, cfg.serie_factura, cfg.proveedor = d.serie_boleta, d.serie_factura, d.proveedor
    if d.token:
        cfg.token_cifrado = facturacion.cifrar(d.token)
    db.add(cfg)
    configuracion.registrar(
        db, colegio_id, quien, "editar", "configuracion", "facturacion", colegio_id,
        f"Comprobantes electrónicos: {'emite' if d.emite else 'no emite'}, RUC {d.ruc or '—'}, "
        f"series {d.serie_boleta} y {d.serie_factura}, proveedor {facturacion.NOMBRE_PROVEEDOR.get(d.proveedor, d.proveedor)}"
        f"{', token cambiado' if d.token else ''}")
    guardar(db)
    return facturacion.config_de(cfg)


@router.get("/facturacion")
def ver_facturacion(s: Sesion = Depends(solo_administrador), db: Session = Depends(get_db)) -> dict:
    return facturacion.config_de(facturacion.config(db, s.colegio.id))


@router.put("/facturacion")
def cambiar_facturacion(d: FacturacionIn, s: Sesion = Depends(solo_administrador), db: Session = Depends(get_db)) -> dict:
    return aplicar_facturacion(db, s.colegio.id, d, s.usuario)


# --- Historial de actividad (solo el administrador) --------------------------------------------

NOMBRE_MODULO = {**MODULOS, "configuracion": "Configuración"}


@router.get("/historial")
def historial(usuario_id: int | None = None, modulo: str | None = None, desde: date | None = None,
              hasta: date | None = None, p: Pagina = Depends(pagina),
              s: Sesion = Depends(solo_administrador), db: Session = Depends(get_db)) -> dict:
    """Lo último primero, por páginas. Las fechas del filtro son días de Lima."""
    cid = s.colegio.id
    q = select(RegistroActividad).where(RegistroActividad.colegio_id == cid)
    if usuario_id is not None:
        q = q.where(RegistroActividad.usuario_id == usuario_id)
    if modulo:
        q = q.where(RegistroActividad.modulo == modulo)
    if desde:
        q = q.where(RegistroActividad.creado_en >= datetime.combine(desde, time(0), LIMA))
    if hasta:
        q = q.where(RegistroActividad.creado_en < datetime.combine(hasta + timedelta(days=1), time(0), LIMA))
    total = contar(db, q)
    filas = db.scalars(recortar(q.order_by(RegistroActividad.creado_en.desc(), RegistroActividad.id.desc()), p)).all()
    personas = db.execute(select(Usuario.id, Usuario.apellidos + ", " + Usuario.nombres)
                          .where(Usuario.colegio_id == cid,
                                 Usuario.id.in_(select(RegistroActividad.usuario_id.distinct()).where(
                                     RegistroActividad.colegio_id == cid)))
                          .order_by(Usuario.apellidos, Usuario.nombres)).all()
    modulos = db.scalars(select(RegistroActividad.modulo.distinct()).where(RegistroActividad.colegio_id == cid)).all()
    return {
        **p.datos(total),
        "items": [{"id": r.id, "creado_en": r.creado_en.isoformat(), "quien": r.quien, "usuario_id": r.usuario_id,
                   "accion": r.accion, "modulo": r.modulo, "modulo_nombre": NOMBRE_MODULO.get(r.modulo, r.modulo),
                   "que": r.que, "objeto_id": r.objeto_id, "resumen": r.resumen} for r in filas],
        "personas": [{"id": i, "nombre": n} for i, n in personas],
        "modulos": sorted(({"clave": m, "nombre": NOMBRE_MODULO.get(m, m)} for m in modulos),
                          key=lambda x: x["nombre"]),
    }
