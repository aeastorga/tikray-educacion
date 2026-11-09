"""Administrador del colegio (antes "Director") y límite de usuarios del personal según el plan."""

import os

from sqlalchemy import func, select, text

from app.db import get_engine
from app.models import Apoderado, Colegio, Rol, Usuario
from tests.conftest import auth, crear_admin, crear_colegio, crear_personal, host, token, token_plataforma
from tests.test_importacion import excel, subir
from tests.test_padron import armar

NUEVO = {"nombre": "IE San Martín", "subdominio": "sanmartin",
         "administrador": {"numero_documento": "12345678", "nombres": "Rosa", "apellidos": "Quispe"}}
MENSAJE = "Tu plan permite {} usuarios. Para más, contacta a Tikray Labs"


def _plataforma(client, db) -> dict:
    crear_admin(db)
    return {"Authorization": f"Bearer {token_plataforma(client)}"}


def _limite(client, hp, cid, maximo):
    r = client.patch(f"/plataforma/colegios/{cid}", headers=hp, json={"max_usuarios": maximo})
    assert r.status_code == 200, r.text
    return r.json()


def _nuevo(client, h, dni, rol_id):
    return client.post("/api/personal", headers=h, json={"numero_documento": dni, "nombres": "Ana", "apellidos": "Paz",
                                                         "rol_id": rol_id})


def _rol(client, h, nombre="Docente") -> int:
    return client.post("/api/roles", headers=h, json={"nombre": nombre}).json()["id"]


def _activo(client, h, u: dict, activo: bool):
    return client.put(f"/api/personal/{u['id']}", headers=h, json={
        "nombres": u["nombres"], "apellidos": u["apellidos"], "rol_id": u["rol_id"], "activo": activo})


# --- Administrador ------------------------------------------------------------------------------------

def test_colegio_nace_con_administrador_que_nadie_edita_ni_borra(client, db):
    hp = _plataforma(client, db)
    r = client.post("/plataforma/colegios", headers=hp, json=NUEVO)
    assert r.status_code == 201, r.text
    creado = r.json()
    assert creado["administrador_usuario"] == "12345678" and creado["administrador_clave_temporal"]
    assert creado["colegio"]["max_usuarios"] is None
    roles = db.scalars(select(Rol).where(Rol.colegio_id == creado["colegio"]["id"])).all()
    assert [(x.nombre, x.es_administrador) for x in roles] == [("Administrador", True)]  # "Director" no se crea

    tok = client.post("/api/auth/ingreso", headers=host("sanmartin"),
                      json={"usuario": "12345678", "clave": creado["administrador_clave_temporal"]}).json()["token"]
    h = auth("sanmartin", tok)
    client.post("/api/auth/cambiar-clave", headers=h,
                json={"clave_actual": creado["administrador_clave_temporal"], "clave_nueva": "ClaveNueva2026"})
    h = auth("sanmartin", token(client, "sanmartin", "12345678", "ClaveNueva2026"))
    yo = client.get("/api/auth/yo", headers=h).json()
    assert yo["rol"] == "Administrador" and yo["es_administrador"] is True and "es_director" not in yo

    rol_admin = roles[0].id
    assert client.put(f"/api/roles/{rol_admin}", headers=h, json={"nombre": "X"}).status_code == 400
    assert client.delete(f"/api/roles/{rol_admin}", headers=h).status_code == 400
    # Ni él mismo cambia su rol ni se desactiva.
    admin = next(p for p in client.get("/api/personal", headers=h).json() if p["usuario"] == "12345678")
    otro_rol = _rol(client, h)
    assert client.put(f"/api/personal/{admin['id']}", headers=h, json={
        "nombres": "Rosa", "apellidos": "Quispe", "rol_id": otro_rol, "activo": True}).status_code == 409
    assert _activo(client, h, admin, False).status_code == 409

    # Alguien del personal, aunque tenga permiso de editar personal y roles, tampoco.
    c = db.get(Colegio, creado["colegio"]["id"])
    crear_personal(db, c, "20000000", {"personal": "editar", "roles": "editar"})
    hs = auth("sanmartin", token(client, "sanmartin", "20000000"))
    assert client.put(f"/api/roles/{rol_admin}", headers=hs, json={"nombre": "X"}).status_code == 400
    assert client.delete(f"/api/roles/{rol_admin}", headers=hs).status_code == 400
    assert _activo(client, hs, admin, False).status_code == 403
    assert client.post(f"/api/personal/{admin['id']}/reiniciar-clave", headers=hs).status_code == 403
    # "Director" ahora es un rol más que crea el administrador, sin nada especial.
    director = client.post("/api/roles", headers=h, json={"nombre": "Director", "permisos": {"padron": "ver"}}).json()
    assert director["es_administrador"] is False and director["permisos"] == {"padron": "ver"}


def test_migracion_renombra_director_y_sube_y_baja(client, db):
    from alembic import command
    from alembic.config import Config

    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    try:
        command.downgrade(cfg, "9ff6e5951cf5")
        with get_engine().begin() as conn:
            cols = set(conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'rol'"))
                       .scalars())
            assert "es_director" in cols and "es_administrador" not in cols
            assert "max_usuarios" not in set(conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'colegio'")).scalars())
            conn.execute(text("INSERT INTO colegio (id, nombre, subdominio, color_primario, color_secundario, estado, "
                              "creado_en) VALUES (1, 'A', 'alfa', '#111111', '#222222', 'activo', now())"))
            conn.execute(text("INSERT INTO rol (colegio_id, nombre, es_director, creado_en) VALUES "
                              "(1, 'Director', true, now()), (1, 'Docente', false, now())"))
            conn.execute(text("INSERT INTO usuario (colegio_id, numero_documento, usuario, nombres, apellidos, "
                              "clave_hash, rol_id, tipo_documento, debe_cambiar_clave, activo, version_sesion, codigo, "
                              "creado_en) SELECT 1, '10000000', '10000000', 'Ana', 'Paz', 'x', id, 'DNI', false, true, "
                              "0, 'ABCDEFGH', now() "
                              "FROM rol WHERE nombre = 'Director'"))
        command.upgrade(cfg, "head")
        with get_engine().begin() as conn:
            assert dict(conn.execute(text("SELECT nombre, es_administrador FROM rol ORDER BY nombre")).all()) == {
                "Administrador": True, "Docente": False}
            # El usuario sigue igual, con el mismo rol (ya renombrado).
            assert conn.execute(text("SELECT r.nombre FROM usuario u JOIN rol r ON r.id = u.rol_id")).scalar() == \
                "Administrador"
            assert conn.execute(text("SELECT max_usuarios FROM colegio")).scalar() is None  # sin límite
        command.downgrade(cfg, "9ff6e5951cf5")
        with get_engine().begin() as conn:
            assert dict(conn.execute(text("SELECT nombre, es_director FROM rol ORDER BY nombre")).all()) == {
                "Director": True, "Docente": False}
    finally:
        command.upgrade(cfg, "head")


# --- Límite de usuarios ---------------------------------------------------------------------------------

def test_limite_crear_desactivar_y_reactivar(client, db):
    c = crear_colegio(db, "alfa")
    hp = _plataforma(client, db)
    h = auth("alfa", token(client, "alfa"))
    rol = _rol(client, h)
    assert client.get("/api/personal/cupo", headers=h).json() == {"activos": 1, "maximo": None}

    assert _limite(client, hp, c.id, 3)["max_usuarios"] == 3
    a = _nuevo(client, h, "20000001", rol).json()["personal"]
    b = _nuevo(client, h, "20000002", rol).json()["personal"]
    db.add(Apoderado(colegio_id=c.id, numero_documento="41234567", nombres="Rosa", apellidos="Mamani"))
    db.commit()  # los padres no cuentan
    assert client.get("/api/personal/cupo", headers=h).json() == {"activos": 3, "maximo": 3}
    r = _nuevo(client, h, "20000003", rol)  # el cuarto: el administrador cuenta
    assert r.status_code == 409 and r.json()["detail"] == MENSAJE.format(3)

    # Desactivar uno libera su cupo.
    assert _activo(client, h, a, False).status_code == 200
    assert client.get("/api/personal/cupo", headers=h).json() == {"activos": 2, "maximo": 3}
    assert _nuevo(client, h, "20000003", rol).status_code == 201
    # Reactivar sobre el límite: 409 y sigue inactivo.
    r = _activo(client, h, a, True)
    assert r.status_code == 409 and r.json()["detail"] == MENSAJE.format(3)
    assert db.get(Usuario, a["id"]).activo is False
    # Editar a alguien activo (sin reactivar) sigue funcionando en el tope.
    assert client.put(f"/api/personal/{b['id']}", headers=h, json={
        "nombres": "Otra", "apellidos": "Persona", "rol_id": rol, "activo": True}).status_code == 200

    # Bajar el límite por debajo de los activos no desactiva a nadie: solo no se agregan más.
    _limite(client, hp, c.id, 1)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Usuario).where(Usuario.colegio_id == c.id, Usuario.activo)) == 3
    assert client.get("/api/personal/cupo", headers=h).json() == {"activos": 3, "maximo": 1}
    assert _nuevo(client, h, "20000004", rol).status_code == 409
    # Sin límite: no hay tope.
    _limite(client, hp, c.id, None)
    for i in range(5, 10):
        assert _nuevo(client, h, f"2000000{i}", rol).status_code == 201


def test_cambiar_limite_queda_en_el_historial(client, db):
    c = crear_colegio(db, "alfa")
    hp = _plataforma(client, db)
    _limite(client, hp, c.id, 20)
    _limite(client, hp, c.id, 20)  # sin cambio: sin línea
    _limite(client, hp, c.id, None)
    h = auth("alfa", token(client, "alfa"))
    filas = client.get("/api/configuracion/historial", headers=h).json()["items"]
    resumenes = [f["resumen"] for f in filas if f["resumen"].startswith("Límite de usuarios")]
    assert sorted(resumenes) == ["Límite de usuarios: 20", "Límite de usuarios: sin límite"]
    assert all(f["quien"] == "Tikray Labs" for f in filas if f["resumen"].startswith("Límite"))
    assert client.patch(f"/plataforma/colegios/{c.id}", headers=hp, json={"max_usuarios": 0}).status_code == 422


def test_solo_tikray_labs_cambia_el_limite(client, db):
    c = crear_colegio(db, "alfa")
    hp = _plataforma(client, db)
    _limite(client, hp, c.id, 5)
    h = auth("alfa", token(client, "alfa"))
    # El administrador del colegio no entra a la plataforma ni lo cambia desde su configuración.
    assert client.patch(f"/plataforma/colegios/{c.id}", headers=h, json={"max_usuarios": None}).status_code == 401
    perfil = client.get("/api/configuracion/perfil", headers=h).json()
    client.put("/api/configuracion/perfil", headers=h, json={**perfil, "max_usuarios": None})
    client.put("/api/configuracion/modulos", headers=h, json={"activos": [], "max_usuarios": None})
    db.expire_all()
    assert db.get(Colegio, c.id).max_usuarios == 5


def test_excel_que_pasa_el_limite_queda_con_error(client, db):
    c = crear_colegio(db, "alfa")
    hp = _plataforma(client, db)
    h, _ = armar(client)
    _rol(client, h)
    _limite(client, hp, c.id, 3)
    hoja = [["DNI", f"4567890{i}", "X", "Y", "Docente", None, None] for i in range(3)]
    r = subir(client, h, excel(personal=hoja)).json()
    assert r["total_errores"] == 1 and r["errores"][0]["hoja"] == "Personal"
    assert MENSAJE.format(3) in r["errores"][0]["mensaje"]
    assert subir(client, h, excel(personal=hoja), "confirmar").status_code == 422
    db.expire_all()
    assert db.scalar(select(Usuario).where(Usuario.numero_documento == "45678900")) is None  # no se aplicó
    # Justo en el límite sí entra; actualizar a quien ya existe no ocupa cupo.
    assert subir(client, h, excel(personal=hoja[:2]), "confirmar").status_code == 200
    r = subir(client, h, excel(personal=[["DNI", "45678900", "Otro", "Nombre", "Docente", None, None]])).json()
    assert r["total_errores"] == 0
    # Sin límite: no hay tope.
    _limite(client, hp, c.id, None)
    assert subir(client, h, excel(personal=hoja + [["DNI", "45678909", "X", "Y", "Docente", None, None]]),
                 ).json()["total_errores"] == 0


def test_limite_y_conteo_son_por_colegio(client, db):
    alfa = crear_colegio(db, "alfa")
    crear_colegio(db, "beta")
    hp = _plataforma(client, db)
    ha, hb = auth("alfa", token(client, "alfa")), auth("beta", token(client, "beta"))
    rol_a, rol_b = _rol(client, ha), _rol(client, hb)
    _limite(client, hp, alfa.id, 2)
    for i in range(4):
        assert _nuevo(client, hb, f"3000000{i}", rol_b).status_code == 201  # beta sin límite
    assert client.get("/api/personal/cupo", headers=ha).json() == {"activos": 1, "maximo": 2}
    assert client.get("/api/personal/cupo", headers=hb).json() == {"activos": 5, "maximo": None}
    assert _nuevo(client, ha, "20000001", rol_a).status_code == 201
    assert _nuevo(client, ha, "20000002", rol_a).status_code == 409
    assert _nuevo(client, hb, "30000009", rol_b).status_code == 201  # el tope de alfa no toca a beta
