"""Normalización de documentos, nombres y contactos. La usan la API y la
carga de Excel, para que una misma regla no exista en dos lugares."""

import re
import unicodedata

# Alumnos y apoderados pueden tener cualquiera; el personal, solo DNI o carné de extranjería.
TIPOS_DOCUMENTO = ("DNI", "CE", "PAS", "OTRO")
TIPOS_DOCUMENTO_PERSONAL = ("DNI", "CE")

_DOC = {
    "DNI": (re.compile(r"^\d{8}$"), "El DNI debe tener 8 dígitos"),
    "CE": (re.compile(r"^[A-Z0-9]{9,12}$"), "El carné de extranjería debe tener de 9 a 12 caracteres"),
    "PAS": (re.compile(r"^[A-Z0-9]{6,15}$"), "El pasaporte debe tener de 6 a 15 caracteres"),
    "OTRO": (re.compile(r"^[A-Z0-9-]{1,15}$"), "El documento debe tener hasta 15 caracteres"),
}
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def clave_texto(texto: str) -> str:
    """Para comparar nombres escritos a mano: 'Primaria ', 'PRIMARIA' y 'primária' son iguales."""
    return " ".join(sin_tildes(str(texto)).lower().split())


def nombre(valor: str) -> str:
    v = " ".join(str(valor or "").split())
    if not v:
        raise ValueError("Es obligatorio")
    if len(v) > 120:
        raise ValueError("Es demasiado largo (máximo 120 caracteres)")
    return v


def tipo_documento(valor: str | None, permitidos: tuple[str, ...] = TIPOS_DOCUMENTO) -> str:
    v = clave_texto(valor or "DNI").upper().replace(".", "")
    v = {"CARNE DE EXTRANJERIA": "CE", "PASAPORTE": "PAS"}.get(v, v)
    if v not in permitidos:
        raise ValueError(f"Tipo de documento no válido (usa {', '.join(permitidos)})")
    return v


def documento(tipo: str, numero: str) -> str:
    v = re.sub(r"[\s.]", "", str(numero or "")).upper()
    if not v:
        raise ValueError("Es obligatorio")
    patron, mensaje = _DOC[tipo]
    if not patron.match(v):
        raise ValueError(mensaje)
    return v


def celular(valor: str | None) -> str | None:
    if valor is None or str(valor).strip() == "":
        return None
    v = re.sub(r"[\s\-()]", "", str(valor))
    v = v.removeprefix("+51") if v.startswith("+51") else v.removeprefix("0051")
    if len(v) == 11 and v.startswith("51"):
        v = v[2:]
    if not re.fullmatch(r"9\d{8}", v):
        raise ValueError("El celular debe tener 9 dígitos y empezar con 9")
    return v


def correo(valor: str | None) -> str | None:
    if valor is None or str(valor).strip() == "":
        return None
    v = str(valor).strip().lower()
    if len(v) > 254 or not _CORREO.match(v):
        raise ValueError("Correo no válido")
    return v
