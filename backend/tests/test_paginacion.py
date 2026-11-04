"""Listas paginadas del panel (cuentas de padres, padrón, cuaderno, lectores de una entrada) y las
secciones de la reunión de padres. Total, páginas, última página incompleta, por_pagina fuera de rango
y aislamiento: el total y el resumen nunca cuentan filas de otro colegio."""

import pytest
from sqlalchemy import select

from app.models import Alumno, Apoderado, EntradaCuaderno, Grado, Matricula, Nivel, Seccion, SeccionDocente, Usuario
from tests.conftest import auth, crear_personal, token
from tests.test_cuaderno import escribir, preparar

EXTRA = 27  # más las 3 de cada escuela: 30 → 25 + 5


@pytest.fixture
def dos(db):
    a, b = preparar(db, "alfa"), preparar(db, "beta", dni_madre="45555555", dni_otro="46666666")
    for i in range(EXTRA):
        db.add(Apoderado(colegio_id=a.colegio.id, numero_documento=f"5{i:07d}", nombres="Ana", apellidos=f"Zeta{i:02d}"))
        al = Alumno(colegio_id=a.colegio.id, numero_documento=f"6{i:07d}", nombres="Luis", apellidos=f"Zeta{i:02d}",
                    codigo=f"ZZ{i:04d}")
        db.add(al)
    for i in range(5):  # beta también tiene de más: nunca deben contarse en alfa
        db.add(Apoderado(colegio_id=b.colegio.id, numero_documento=f"7{i:07d}", nombres="Beto", apellidos="Beta"))
    db.commit()
    return a, b


@pytest.fixture
def h(client, dos):
    return auth("alfa", token(client, "alfa"))


@pytest.fixture
def hb(client, dos):
    return auth("beta", token(client, "beta"))


def _paginas(client, h, ruta, clave):
    p1 = client.get(f"{ruta}?por_pagina=25", headers=h).json()
    p2 = client.get(f"{ruta}?por_pagina=25&pagina=2", headers=h).json()
    p3 = client.get(f"{ruta}?por_pagina=25&pagina=3", headers=h).json()
    return p1, p2, p3, clave


@pytest.mark.parametrize("ruta,clave", [("/api/familias/apoderados", "filas"), ("/api/padron/alumnos", "alumnos")])
def test_paginas_total_y_ultima_incompleta(client, h, ruta, clave):
    p1, p2, p3, _ = _paginas(client, h, ruta, clave)
    assert (p1["total"], p1["paginas"], p1["pagina"], p1["por_pagina"]) == (30, 2, 1, 25)
    assert len(p1[clave]) == 25 and len(p2[clave]) == 5 and p3[clave] == []
    assert not {x["id"] for x in p1[clave]} & {x["id"] for x in p2[clave]}
    assert client.get(ruta, headers=h).json()["por_pagina"] == 25  # por defecto


@pytest.mark.parametrize("ruta", ["/api/familias/apoderados", "/api/padron/alumnos", "/api/cuaderno/entradas"])
@pytest.mark.parametrize("consulta", ["por_pagina=101", "por_pagina=0", "pagina=0", "pagina=-1", "por_pagina=x"])
def test_fuera_de_rango_es_422(client, h, ruta, consulta):
    assert client.get(f"{ruta}?{consulta}", headers=h).status_code == 422


def test_cien_por_pagina_es_el_maximo(client, h):
    r = client.get("/api/familias/apoderados?por_pagina=100", headers=h).json()
    assert len(r["filas"]) == 30 and r["paginas"] == 1


def test_resumen_de_familias_es_de_todo_el_colegio_y_solo_del_suyo(client, h, hb):
    r = client.get("/api/familias/apoderados?q=zeta00", headers=h).json()
    assert r["total"] == 1
    # Madre y otro con cuenta activa; padre y los 27 nuevos sin cuenta. Nada de beta.
    assert r["resumen"] == {"total": 30, "activas": 2, "avisos": 0, "por_aprobar": 0, "sin_cuenta": 28,
                            "bloqueadas": 0}
    rb = client.get("/api/familias/apoderados", headers=hb).json()
    assert rb["total"] == 8 and rb["resumen"]["total"] == 8
    assert all(x["numero_documento"] not in {"41234567", "42222222"} for x in rb["filas"])


def test_familias_separa_documento_e_hijos_con_seccion_y_nivel(client, h, dos):
    a, _ = dos
    fila = next(x for x in client.get("/api/familias/apoderados?q=41234567", headers=h).json()["filas"])
    assert (fila["tipo_documento"], fila["numero_documento"]) == ("DNI", "41234567")
    assert {x["seccion"] for x in fila["hijos"]} == {"Primaria · 1° A", "Primaria · 1° B"}
    assert client.get("/api/familias/apoderados?estado=otro", headers=h).status_code == 422


def test_padron_filtra_por_estado_y_cuenta_apoderados(client, db, h, dos):
    a, _ = dos
    r = client.get("/api/padron/alumnos?estado=sin_matricula&por_pagina=100", headers=h).json()
    assert r["total"] == EXTRA
    con_padres = {x["id"]: x["apoderados"] for x in client.get("/api/padron/alumnos?q=Ape0", headers=h).json()["alumnos"]}
    assert con_padres == {a.a1.id: 2}
    db.get(Alumno, a.a3.id).activo = False
    db.commit()
    assert client.get("/api/padron/alumnos?estado=retirado", headers=h).json()["total"] == 1


def test_cuaderno_por_paginas_y_aislado(client, db, h, hb, dos):
    a, b = dos
    director = db.scalar(select(Usuario).where(Usuario.colegio_id == a.colegio.id))
    db.add_all([EntradaCuaderno(colegio_id=a.colegio.id, creado_por_id=director.id, tipo="comunicado",
                                alcance="colegio", titulo=f"Aviso {i}") for i in range(30)])
    db.commit()
    p1 = client.get("/api/cuaderno/entradas?por_pagina=25", headers=h).json()
    p2 = client.get("/api/cuaderno/entradas?por_pagina=25&pagina=2", headers=h).json()
    assert (p1["total"], p1["paginas"], len(p1["entradas"]), len(p2["entradas"])) == (30, 2, 25, 5)
    assert p1["entradas"][0]["titulo"] == "Aviso 29"  # lo último primero
    assert client.get("/api/cuaderno/entradas", headers=hb).json()["total"] == 0


def test_lectores_por_paginas_y_aislados(client, h, hb, dos):
    eid = escribir(client, h, tipo="comunicado", alcance="colegio", pide_firma=True).json()["id"]
    r = client.get(f"/api/cuaderno/entradas/{eid}/lectores?por_pagina=2", headers=h).json()
    # Una fila por alumno y apoderado: la madre de dos hermanos, el padre y el otro apoderado.
    assert (r["total"], r["paginas"], len(r["filas"])) == (4, 2, 2)
    assert client.get(f"/api/cuaderno/entradas/{eid}/lectores?pagina=2&por_pagina=2", headers=h).json()["filas"]
    assert client.get(f"/api/cuaderno/entradas/{eid}/lectores", headers=hb).status_code == 404
    assert client.get(f"/api/cuaderno/entradas/{eid}/lectores?por_pagina=500", headers=h).status_code == 422
    det = client.get(f"/api/cuaderno/entradas/{eid}", headers=h).json()
    assert det["familias"] == {"total": 3, "vieron": 0, "firmaron": 0} and "lectores" not in det


def test_secciones_de_reunion_con_nivel_docente_y_alumnos(client, db, h, hb, dos):
    a, b = dos
    tutor = crear_personal(db, a.colegio, "20000001", {"reuniones": "editar"})
    tutor.nombres, tutor.apellidos = "Rosa", "Quispe"
    db.add(SeccionDocente(colegio_id=a.colegio.id, seccion_id=a.sec_b.id, usuario_id=tutor.id))
    db.commit()
    lista = client.get("/api/reuniones/secciones", headers=h).json()
    assert [(x["nivel"], x["nombre"]) for x in lista] == [("Primaria", "1° A"), ("Primaria", "1° B"),
                                                         ("Secundaria", "1° A")]
    por_id = {x["id"]: x for x in lista}
    assert por_id[a.sec_b.id]["docente"] == "Rosa Quispe" and por_id[a.sec_a.id]["docente"] is None
    assert por_id[a.sec_a.id]["alumnos"] == 1 and por_id[a.sec_a.id]["fichas_pendientes"] == 0
    # Beta: solo las suyas, con sus cantidades.
    lb = client.get("/api/reuniones/secciones", headers=hb).json()
    assert {x["id"] for x in lb} == {b.sec_a.id, b.sec_b.id, b.sec_secundaria.id}
    assert all(x["docente"] is None for x in lb)
