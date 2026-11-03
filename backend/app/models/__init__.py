from app.models.asistencia import (AsistenciaAlumno, AsistenciaPersonal, ColaAviso, ConfigAsistencia,
                                   LicenciaPersonal, Marcacion)
from app.models.colegio import Colegio
from app.models.cuaderno import (AdjuntoCuaderno, DestinoCuaderno, EntradaCuaderno, MensajeCuaderno,
                                  SeccionDocente)
from app.models.familias import (CambioApoderado, ConfigFamilias, ConsentimientoApoderado, CuentaFamilia,
                                 EntregaAviso, InvitacionFamilia, PasskeyFamilia, RetoUsado, SuscripcionPush)
from app.models.padron import (AlumnoApoderado, Alumno, AnioEscolar, Apoderado, DiaNoLectivo, Grado,
                               Matricula, Nivel, Seccion, Turno)
from app.models.personal import PermisoRol, Rol, Usuario
from app.models.plataforma import AdminPlataforma, IntentoFallido

__all__ = [
    "AdjuntoCuaderno", "DestinoCuaderno", "EntradaCuaderno", "MensajeCuaderno", "SeccionDocente",
    "AdminPlataforma", "Alumno", "AlumnoApoderado", "AnioEscolar", "Apoderado", "AsistenciaAlumno",
    "AsistenciaPersonal", "CambioApoderado", "ColaAviso", "Colegio", "ConfigAsistencia", "ConfigFamilias",
    "ConsentimientoApoderado", "CuentaFamilia", "EntregaAviso", "InvitacionFamilia", "PasskeyFamilia",
    "RetoUsado", "SuscripcionPush", "DiaNoLectivo", "Grado", "IntentoFallido",
    "LicenciaPersonal", "Marcacion", "Matricula", "Nivel", "PermisoRol", "Rol", "Seccion", "Turno", "Usuario",
]
