from app.models.asistencia import (AsistenciaAlumno, AsistenciaPersonal, ColaAviso, ConfigAsistencia,
                                   LicenciaPersonal, Marcacion)
from app.models.colegio import Colegio
from app.models.padron import (AlumnoApoderado, Alumno, AnioEscolar, Apoderado, DiaNoLectivo, Grado,
                               Matricula, Nivel, Seccion, Turno)
from app.models.personal import PermisoRol, Rol, Usuario
from app.models.plataforma import AdminPlataforma

__all__ = [
    "AdminPlataforma", "Alumno", "AlumnoApoderado", "AnioEscolar", "Apoderado", "AsistenciaAlumno",
    "AsistenciaPersonal", "ColaAviso", "Colegio", "ConfigAsistencia", "DiaNoLectivo", "Grado",
    "LicenciaPersonal", "Marcacion", "Matricula", "Nivel", "PermisoRol", "Rol", "Seccion", "Turno", "Usuario",
]
