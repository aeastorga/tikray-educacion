from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import codigos, pdf, validacion
from app.comun import guardar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.models import Rol, Turno, Usuario
from app.proteccion import generar_clave_temporal
from app.routers.importacion import imagen_pdf
from app.seguridad import hashear_clave

router = APIRouter(prefix="/personal", tags=["personal"])


class DocumentoPersonal(BaseModel):
    tipo_documento: str = "DNI"
    numero_documento: str
    nombres: str
    apellidos: str

    @model_validator(mode="after")
    def _normalizar(self):
        self.tipo_documento = validacion.tipo_documento(self.tipo_documento, validacion.TIPOS_DOCUMENTO_PERSONAL)
        self.numero_documento = validacion.documento(self.tipo_documento, self.numero_documento)
        self.nombres = validacion.nombre(self.nombres)
        self.apellidos = validacion.nombre(self.apellidos)
        return self


class NuevoPersonal(DocumentoPersonal):
    rol_id: int
    usuario: str | None = Field(default=None, max_length=60)  # por defecto, el número de documento


class PersonalOut(BaseModel):
    id: int
    tipo_documento: str
    numero_documento: str
    usuario: str
    nombres: str
    apellidos: str
    rol_id: int
    rol: str
    turno_id: int | None
    codigo: str
    activo: bool
    debe_cambiar_clave: bool


class EdicionPersonal(BaseModel):
    nombres: str
    apellidos: str
    rol_id: int
    turno_id: int | None = None  # con turno se le calcula tardanza y falta automática
    activo: bool = True

    @model_validator(mode="after")
    def _normalizar(self):
        self.nombres = validacion.nombre(self.nombres)
        self.apellidos = validacion.nombre(self.apellidos)
        return self


class ConClaveTemporal(BaseModel):
    personal: PersonalOut
    clave_temporal: str  # se muestra una sola vez


def _salida(u: Usuario) -> PersonalOut:
    return PersonalOut(
        id=u.id, tipo_documento=u.tipo_documento, numero_documento=u.numero_documento, usuario=u.usuario, nombres=u.nombres, apellidos=u.apellidos,
        rol_id=u.rol_id, rol=u.rol.nombre, turno_id=u.turno_id, codigo=u.codigo, activo=u.activo, debe_cambiar_clave=u.debe_cambiar_clave,
    )


def _persona(db: Session, colegio_id: int, usuario_id: int) -> Usuario:
    u = db.scalar(select(Usuario).where(Usuario.id == usuario_id, Usuario.colegio_id == colegio_id))
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona no encontrada")
    return u


@router.get("")
def listar(s: Sesion = Depends(requerir_permiso("personal")), db: Session = Depends(get_db)) -> list[PersonalOut]:
    filas = db.scalars(
        select(Usuario).where(Usuario.colegio_id == s.colegio.id).order_by(Usuario.apellidos, Usuario.nombres)
    )
    return [_salida(u) for u in filas]


@router.post("", status_code=201)
def crear(
    datos: NuevoPersonal,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> ConClaveTemporal:
    rol = db.scalar(select(Rol).where(Rol.id == datos.rol_id, Rol.colegio_id == s.colegio.id))
    if rol is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rol no encontrado")
    if rol.es_director and not s.usuario.rol.es_director:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director asigna el rol de director")
    clave = generar_clave_temporal()
    u = Usuario(
        colegio_id=s.colegio.id, tipo_documento=datos.tipo_documento,
        numero_documento=datos.numero_documento,
        usuario=(datos.usuario or datos.numero_documento).strip(),
        nombres=datos.nombres, apellidos=datos.apellidos, rol=rol,
        clave_hash=hashear_clave(clave), debe_cambiar_clave=True,
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe personal con ese documento o usuario")
    return ConClaveTemporal(personal=_salida(u), clave_temporal=clave)


@router.post("/{usuario_id}/reiniciar-clave")
def reiniciar_clave(
    usuario_id: int,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> ConClaveTemporal:
    u = _persona(db, s.colegio.id, usuario_id)
    if u.rol.es_director and not s.usuario.rol.es_director:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director reinicia la clave de un director")
    clave = generar_clave_temporal()
    u.clave_hash = hashear_clave(clave)
    u.debe_cambiar_clave = True
    u.version_sesion += 1
    db.commit()
    return ConClaveTemporal(personal=_salida(u), clave_temporal=clave)


@router.put("/{usuario_id}")
def editar(
    usuario_id: int, datos: EdicionPersonal,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> PersonalOut:
    u = _persona(db, s.colegio.id, usuario_id)
    rol = db.scalar(select(Rol).where(Rol.id == datos.rol_id, Rol.colegio_id == s.colegio.id))
    if rol is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rol no encontrado")
    if (u.rol.es_director or rol.es_director) and not s.usuario.rol.es_director:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director cambia a un director")
    if u.id == s.usuario.id and (rol.id != u.rol_id or not datos.activo):
        raise HTTPException(status.HTTP_409_CONFLICT, "No puedes cambiar tu propio rol ni desactivarte")
    if datos.turno_id is not None and db.scalar(
            select(Turno.id).where(Turno.id == datos.turno_id, Turno.colegio_id == s.colegio.id)) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Turno no encontrado")
    u.nombres, u.apellidos, u.rol, u.turno_id = datos.nombres, datos.apellidos, rol, datos.turno_id
    if u.activo and not datos.activo:
        u.version_sesion += 1  # quien deja el colegio pierde la sesión al instante
    u.activo = datos.activo
    guardar(db)
    return _salida(u)


@router.post("/{usuario_id}/nuevo-codigo")
def nuevo_codigo(
    usuario_id: int,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> dict:
    """Para un carnet perdido: el código anterior deja de servir en la portería."""
    u = _persona(db, s.colegio.id, usuario_id)
    u.codigo = codigos.aleatorio()
    guardar(db, repetido="Intenta de nuevo")
    return {"codigo": u.codigo}


@router.get("/carnets")
def carnets(
    usuario_id: int | None = None,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> Response:
    """Carnets del personal activo (o de una persona) para marcar su asistencia en la portería."""
    consulta = select(Usuario).where(Usuario.colegio_id == s.colegio.id, Usuario.activo)
    if usuario_id is not None:
        consulta = consulta.where(Usuario.id == _persona(db, s.colegio.id, usuario_id).id)
    filas = db.scalars(consulta.order_by(Usuario.apellidos, Usuario.nombres)).all()
    contenido = pdf.carnets(imagen_pdf(s.colegio), [
        pdf.FilaCarnet(apellidos=u.apellidos, nombres=u.nombres, seccion=u.rol.nombre, anio=None,
                       qr=codigos.contenido_qr(u.codigo, personal=True), codigo=u.codigo)
        for u in filas
    ])
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="carnets-personal.pdf"'})
