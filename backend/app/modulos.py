"""Catálogo de módulos sobre los que el administrador da permisos a cada rol."""

MODULOS: dict[str, str] = {
    "configuracion": "Configuración e imagen del colegio",
    "roles": "Roles y permisos",
    "personal": "Personal del colegio",
    "padron": "Padrón de alumnos y apoderados",
    "asistencia": "Asistencia",
    "avisos": "Avisos a familias",
    "cuaderno": "Cuaderno de control",
    "familias": "Cuentas de padres",
    "reuniones": "Reunión de padres",
    "pensiones": "Pensiones y cuotas",
    "caja": "Caja y gastos",
    "recojo": "Recojo seguro",
    "calendario": "Calendario escolar",
    "autorizaciones": "Autorizaciones",
}

NIVELES = ("ver", "editar")
