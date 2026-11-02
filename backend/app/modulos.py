"""Catálogo de módulos sobre los que el director da permisos a cada rol."""

MODULOS: dict[str, str] = {
    "configuracion": "Configuración e imagen del colegio",
    "roles": "Roles y permisos",
    "personal": "Personal del colegio",
    "padron": "Padrón de alumnos y apoderados",
    "asistencia": "Asistencia",
    "avisos": "Avisos a familias",
    "cuaderno": "Cuaderno de control",
    "familias": "Cuentas de padres",
}

NIVELES = ("ver", "editar")
