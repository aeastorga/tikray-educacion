"""Notificaciones con diseño propio: el tipo de aviso en el título, el logo del colegio como ícono (o el de la
app) y la insignia. Los textos de los avisos no cambian. Nunca sale el logo de otro colegio."""

from datetime import date

import pytest
from sqlalchemy import select

from app import avisos
from app.almacenamiento import get_almacenamiento
from app.models import Alumno, ColaAviso, Colegio, EntregaAviso
from tests.conftest import crear_familia, lunes
from tests.test_asistencia import en, marcar, preparar
from tests.test_familias import Push, pronto, suscribir

TITULOS = [("ingreso", "Ingreso"), ("tarde", "Llegó tarde"), ("salida", "Salida"), ("falta", "Falta"),
           ("cuaderno", "Cuaderno"), ("cobro", "Pagos"), ("calendario", "Calendario"),
           ("autorizar", "Autorización"), ("cuenta", "Tu cuenta")]


def aviso(tipo: str) -> ColaAviso:
    datos = {"hora": "07:40", "minutos_tarde": 5, "mensaje": "Texto de prueba."}
    return ColaAviso(id=7, tipo=tipo, colegio_id=1, alumno_id=None if tipo in avisos.ESPERAN_SILENCIO + ("cuenta",)
                     else 3, apoderado_id=4, fecha=date(2026, 3, 2), datos=datos)


@pytest.mark.parametrize(("tipo", "nombre"), TITULOS)
def test_cada_tipo_lleva_su_titulo_con_el_colegio(tipo, nombre):
    colegio = Colegio(nombre="Colegio Demo Tikray")
    m = avisos.mensaje(aviso(tipo), colegio, Alumno(nombres="Lucía Belén", apellidos="Quispe"))
    assert m["titulo"] == f"{nombre} · Colegio Demo Tikray"
    assert m["icono"] == "/icono-192.png" and m["insignia"] == "/insignia-96.png"


def test_los_textos_no_cambian():
    alumno = Alumno(nombres="Lucía Belén", apellidos="Quispe")
    c = Colegio(nombre="Colegio Demo Tikray")
    assert avisos.mensaje(aviso("ingreso"), c, alumno)["cuerpo"] == "Lucía ingresó al colegio a las 07:40."
    assert avisos.mensaje(aviso("tarde"), c, alumno)["cuerpo"] == "Lucía llegó tarde: ingresó a las 07:40 (5 min)."
    assert avisos.mensaje(aviso("cuaderno"), c, None)["cuerpo"] == "Texto de prueba."


def test_nombre_largo_se_corta_el_nombre_y_no_el_tipo():
    largo = "Institución Educativa Particular San Juan Bautista de la Salle del Cusco"
    titulo = avisos.mensaje(aviso("tarde"), Colegio(nombre=largo), Alumno(nombres="Ana", apellidos="R"))["titulo"]
    assert titulo.startswith("Llegó tarde · Institución Educativa")
    assert titulo.endswith("…") and len(titulo) == len("Llegó tarde · ") + avisos.LARGO_NOMBRE


def test_icono_es_el_logo_del_colegio_si_tiene():
    c = Colegio(nombre="Colegio Demo Tikray", logo_clave="logos/1/abc.png")
    m = avisos.mensaje(aviso("cuenta"), c, None)
    assert m["icono"] == get_almacenamiento().url("logos/1/abc.png") and m["icono"].endswith("logos/1/abc.png")


def test_cada_familia_ve_el_logo_y_el_titulo_de_su_colegio(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    a.colegio.logo_clave = "logos/alfa/escudo.png"  # beta no tiene logo
    db.commit()
    crear_familia(db, a.colegio, dni="41234567", alumnos=a.alumnos[:1])
    crear_familia(db, b.colegio, dni="42222222", alumnos=b.alumnos[:1])
    hf_a = suscribir(client, "alfa", dni="41234567", endpoint="https://push.example/alfa")
    suscribir(client, "beta", dni="42222222", endpoint="https://push.example/beta")
    marcar(db, a, en(lunes(), 7, 40))
    marcar(db, b, en(lunes(), 7, 41))
    push = Push()
    assert avisos.procesar_cola(db, push, ahora=pronto()) == 2
    por_celular = dict(push.enviados)
    assert por_celular["https://push.example/alfa"]["titulo"] == "Ingreso · Colegio alfa"
    assert por_celular["https://push.example/alfa"]["icono"] == get_almacenamiento().url("logos/alfa/escudo.png")
    assert por_celular["https://push.example/beta"]["titulo"] == "Ingreso · Colegio beta"
    assert por_celular["https://push.example/beta"]["icono"] == "/icono-192.png"  # no el logo de alfa
    marcados = {x.colegio_id: x for x in db.scalars(select(ColaAviso))}
    momento = marcados[a.colegio.id].momento
    assert por_celular["https://push.example/alfa"]["momento"] == int(momento.timestamp() * 1000)
    # El historial guarda y muestra el título nuevo.
    assert {e.titulo for e in db.scalars(select(EntregaAviso))} == {"Ingreso · Colegio alfa", "Ingreso · Colegio beta"}
    assert client.get("/api/familia/avisos", headers=hf_a).json()[0]["titulo"] == "Ingreso · Colegio alfa"
