"""PDF de carnets (con QR), cartas de acceso del personal, fichas de la reunión y recibos de caja."""

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

# Carnet tamaño tarjeta (CR80) y 10 por hoja A4.
ANCHO_CARNET, ALTO_CARNET = 85.6 * mm, 54 * mm
COLUMNAS, FILAS = 2, 5


@dataclass
class Imagen:
    nombre: str
    color_primario: str
    logo: bytes | None


@dataclass
class FilaCarnet:
    apellidos: str
    nombres: str
    seccion: str
    anio: int | None  # None en los carnets del personal
    qr: str
    codigo: str


@dataclass
class FilaCarta:
    nombres: str
    apellidos: str
    usuario: str
    clave_temporal: str


def _qr(c: Canvas, contenido: str, x: float, y: float, lado: float) -> None:
    widget = QrCodeWidget(contenido, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    dibujo = Drawing(lado, lado, transform=[lado / (x2 - x1), 0, 0, lado / (y2 - y1), 0, 0])
    dibujo.add(widget)
    renderPDF.draw(dibujo, c, x, y)


def _ajustar(texto: str, fuente: str, tamano: float, ancho: float, minimo: float = 6) -> float:
    """Achica la letra hasta que el texto entre en el ancho."""
    while tamano > minimo and stringWidth(texto, fuente, tamano) > ancho:
        tamano -= 0.5
    return tamano


def _lineas(texto: str, fuente: str, tamano: float, ancho: float, maximo: int = 2) -> tuple[list[str], float]:
    """Parte el texto por palabras en hasta `maximo` líneas. Solo si aun así no
    entra (una palabra muy larga, o más texto que líneas), achica la letra."""
    while True:
        lineas: list[str] = []
        for palabra in texto.split():
            if lineas and stringWidth(f"{lineas[-1]} {palabra}", fuente, tamano) <= ancho:
                lineas[-1] = f"{lineas[-1]} {palabra}"
            else:
                lineas.append(palabra)
        cabe = len(lineas) <= maximo and all(stringWidth(l, fuente, tamano) <= ancho for l in lineas)
        if cabe or tamano <= 6:
            return lineas[:maximo], tamano
        tamano -= 0.5


def _logo(imagen: Imagen) -> ImageReader | None:
    if not imagen.logo:
        return None
    try:
        return ImageReader(BytesIO(imagen.logo))
    except Exception:  # un logo dañado no debe impedir imprimir
        return None


def carnets(imagen: Imagen, filas: list[FilaCarnet]) -> bytes:
    salida = BytesIO()
    c = Canvas(salida, pagesize=A4)
    c.setTitle(f"Carnets · {imagen.nombre}")
    ancho_hoja, alto_hoja = A4
    margen_x = (ancho_hoja - COLUMNAS * ANCHO_CARNET) / 2
    margen_y = (alto_hoja - FILAS * ALTO_CARNET) / 2
    color = HexColor(imagen.color_primario)
    logo = _logo(imagen)
    por_hoja = COLUMNAS * FILAS

    for i, f in enumerate(filas):
        if i and i % por_hoja == 0:
            c.showPage()
        pos = i % por_hoja
        x = margen_x + (pos % COLUMNAS) * ANCHO_CARNET
        y = alto_hoja - margen_y - (pos // COLUMNAS + 1) * ALTO_CARNET

        # Borde fino para recortar.
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.setLineWidth(0.3)
        c.rect(x, y, ANCHO_CARNET, ALTO_CARNET)

        # Franja superior con logo y nombre del colegio.
        franja = 12 * mm
        c.setFillColor(color)
        c.rect(x, y + ALTO_CARNET - franja, ANCHO_CARNET, franja, stroke=0, fill=1)
        texto_x = x + 3 * mm
        if logo:
            lado = franja - 3 * mm
            c.drawImage(logo, x + 2 * mm, y + ALTO_CARNET - franja + 1.5 * mm, lado, lado,
                        preserveAspectRatio=True, mask="auto")
            texto_x += lado + 1 * mm
        c.setFillColor(white)
        ancho_nombre = x + ANCHO_CARNET - 3 * mm - texto_x
        t = _ajustar(imagen.nombre, "Helvetica-Bold", 10, ancho_nombre)
        c.setFont("Helvetica-Bold", t)
        c.drawString(texto_x, y + ALTO_CARNET - franja / 2 - t / 3, imagen.nombre)

        # Datos del alumno a la izquierda, QR a la derecha.
        lado_qr = 28 * mm
        qr_x = x + ANCHO_CARNET - lado_qr - 2 * mm
        qr_y = y + 4 * mm
        _qr(c, f.qr, qr_x, qr_y, lado_qr)
        ancho_texto = qr_x - x - 5 * mm
        c.setFillColorRGB(0.1, 0.1, 0.1)
        fila_y = y + ALTO_CARNET - franja - 7 * mm
        # Apellidos y nombres en hasta dos líneas cada uno; lo de abajo baja si hacen falta.
        for texto, fuente, tamano in ((f.apellidos.upper(), "Helvetica-Bold", 11), (f.nombres, "Helvetica", 10)):
            lineas, t = _lineas(texto, fuente, tamano, ancho_texto)
            c.setFont(fuente, t)
            for linea in lineas:
                c.drawString(x + 3 * mm, fila_y, linea)
                fila_y -= t * 0.42 * mm
            fila_y -= 0.8 * mm
        fila_y -= 1.5 * mm
        c.setFont("Helvetica", _ajustar(f.seccion, "Helvetica", 8.5, ancho_texto))
        c.drawString(x + 3 * mm, fila_y, f.seccion)
        if f.anio:
            c.setFont("Helvetica", 8.5)
            c.drawString(x + 3 * mm, fila_y - 4 * mm, f"Año escolar {f.anio}")
        c.setFont("Courier-Bold", 9)
        c.drawCentredString(qr_x + lado_qr / 2, y + 1.5 * mm, f.codigo)

    if not filas:
        c.setFont("Helvetica", 12)
        c.drawString(20 * mm, alto_hoja - 30 * mm, "No hay alumnos para imprimir.")
    c.save()
    return salida.getvalue()


def cartas_personal(imagen: Imagen, direccion: str, filas: list[FilaCarta]) -> bytes:
    """Una hoja por persona con su usuario y clave temporal, para entregar en mano."""
    salida = BytesIO()
    c = Canvas(salida, pagesize=A4)
    c.setTitle(f"Accesos del personal · {imagen.nombre}")
    ancho, alto = A4
    color = HexColor(imagen.color_primario)
    logo = _logo(imagen)
    izq = 25 * mm

    for i, f in enumerate(filas):
        if i:
            c.showPage()
        y = alto - 25 * mm
        if logo:
            c.drawImage(logo, izq, y - 18 * mm, 18 * mm, 18 * mm, preserveAspectRatio=True, mask="auto")
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", _ajustar(imagen.nombre, "Helvetica-Bold", 16, ancho - 2 * izq - 22 * mm))
        c.drawString(izq + (22 * mm if logo else 0), y - 10 * mm, imagen.nombre)
        c.setStrokeColor(color)
        c.setLineWidth(1.5)
        c.line(izq, y - 22 * mm, ancho - izq, y - 22 * mm)

        c.setFillColorRGB(0.1, 0.1, 0.1)
        y -= 38 * mm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(izq, y, "Tu acceso al sistema del colegio")
        y -= 12 * mm
        c.setFont("Helvetica", 11)
        c.drawString(izq, y, f"Estimado(a) {f.nombres} {f.apellidos}:")
        y -= 8 * mm
        c.drawString(izq, y, "Con estos datos puedes ingresar como personal del colegio.")

        # Recuadro con los datos.
        y -= 10 * mm
        alto_caja = 42 * mm
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.setLineWidth(0.8)
        c.roundRect(izq, y - alto_caja, ancho - 2 * izq, alto_caja, 4 * mm)
        etiquetas = [("Dirección", direccion), ("Usuario", f.usuario), ("Clave temporal", f.clave_temporal)]
        fila_y = y - 11 * mm
        for etiqueta, valor in etiquetas:
            c.setFont("Helvetica", 10)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.drawString(izq + 6 * mm, fila_y, etiqueta)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            fuente = "Courier-Bold" if etiqueta != "Dirección" else "Helvetica-Bold"
            # Sin pisar el QR de la derecha, aunque el dominio propio sea largo.
            c.setFont(fuente, _ajustar(valor, fuente, 13, ancho - izq - 38 * mm - (izq + 45 * mm)))
            c.drawString(izq + 45 * mm, fila_y, valor)
            fila_y -= 11 * mm
        _qr(c, direccion, ancho - izq - 34 * mm, y - alto_caja + 4 * mm, 30 * mm)

        y -= alto_caja + 14 * mm
        c.setFont("Helvetica", 11)
        for linea in (
            "1. Entra a la dirección (o escanea el código) y elige \"Soy personal del colegio\".",
            "2. Escribe tu usuario y la clave temporal.",
            "3. El sistema te pedirá crear tu propia clave. Desde ahí, la temporal ya no sirve.",
            "",
            "Esta hoja es personal: no la compartas. Si la pierdes, pide en dirección",
            "que reinicien tu clave.",
        ):
            c.drawString(izq, y, linea)
            y -= 7 * mm

    c.save()
    return salida.getvalue()


@dataclass
class ApoderadoFicha:
    documento: str
    nombres: str
    apellidos: str
    parentesco: str
    celular: str
    correo: str


@dataclass
class FichaAlumno:
    nombre: str
    documento: str
    apoderados: list[ApoderadoFicha]


def _envolver(texto: str, fuente: str, tamano: float, ancho: float) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if stringWidth(prueba, fuente, tamano) <= ancho:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    return lineas + ([actual] if actual else [])


def fichas_reunion(imagen: Imagen, seccion: str, consentimiento: str, alumnos: list[FichaAlumno]) -> bytes:
    """Respaldo en papel del modo reunión: una hoja por alumno con lo que el colegio tiene de sus
    apoderados, una columna para corregir, un recuadro para otro apoderado y el consentimiento para firmar."""
    salida = BytesIO()
    c = Canvas(salida, pagesize=A4)
    c.setTitle(f"Fichas de apoderados · {seccion} · {imagen.nombre}")
    ancho, alto = A4
    color = HexColor(imagen.color_primario)
    logo = _logo(imagen)
    izq, util = 18 * mm, ancho - 36 * mm
    campos = [("Documento", "documento"), ("Nombres", "nombres"), ("Apellidos", "apellidos"),
              ("Parentesco", "parentesco"), ("Celular", "celular"), ("Correo", "correo")]
    fila_alto = 7.5 * mm

    def tabla(y: float, titulo: str, ap: ApoderadoFicha | None) -> float:
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(izq, y, titulo)
        y -= 3 * mm
        col1, col2 = izq + 26 * mm, izq + 26 * mm + (util - 26 * mm) / 2
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(col1 + 1.5 * mm, y - 3.5 * mm, "Registrado en el colegio" if ap else "")
        c.drawString(col2 + 1.5 * mm, y - 3.5 * mm, "Corrección (solo si cambió)" if ap else "Escribe aquí")
        y -= 5 * mm
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.setLineWidth(0.6)
        for etiqueta, campo in campos:
            c.rect(izq, y - fila_alto, util, fila_alto)
            c.line(col1, y, col1, y - fila_alto)
            if ap:
                c.line(col2, y, col2, y - fila_alto)
            c.setFillColorRGB(0.35, 0.35, 0.35)
            c.setFont("Helvetica", 9)
            c.drawString(izq + 1.5 * mm, y - 5 * mm, etiqueta)
            if ap:
                valor = getattr(ap, campo) or "—"
                c.setFillColorRGB(0.1, 0.1, 0.1)
                c.setFont("Helvetica", _ajustar(valor, "Helvetica", 9.5, col2 - col1 - 3 * mm))
                c.drawString(col1 + 1.5 * mm, y - 5 * mm, valor)
            y -= fila_alto
        return y - 6 * mm

    for i, a in enumerate(alumnos):
        if i:
            c.showPage()
        y = alto - 18 * mm
        if logo:
            c.drawImage(logo, izq, y - 14 * mm, 14 * mm, 14 * mm, preserveAspectRatio=True, mask="auto")
        x = izq + (18 * mm if logo else 0)
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", _ajustar(imagen.nombre, "Helvetica-Bold", 14, util - 60 * mm))
        c.drawString(x, y - 6 * mm, imagen.nombre)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont("Helvetica", 10)
        c.drawString(x, y - 12 * mm, f"Ficha del apoderado · Reunión de padres · {seccion}")
        c.setStrokeColor(color)
        c.setLineWidth(1.2)
        c.line(izq, y - 17 * mm, ancho - izq, y - 17 * mm)

        y -= 25 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(izq, y, _recortar(f"Alumno(a): {a.nombre}", "Helvetica-Bold", 11, util - 40 * mm))
        c.setFont("Helvetica", 10)
        c.drawRightString(ancho - izq, y, a.documento)
        y -= 9 * mm
        for n, ap in enumerate(a.apoderados[:2]):
            y = tabla(y, f"Apoderado {n + 1}", ap)
        for n in range(len(a.apoderados[:2]), 2):
            y = tabla(y, "Otro apoderado (si no figura arriba)" if a.apoderados else f"Apoderado {n + 1}", None)

        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(izq, y, "Consentimiento (Ley 29733)")
        y -= 5 * mm
        c.setFont("Helvetica", 8.5)
        for linea in _envolver(consentimiento, "Helvetica", 8.5, util):
            c.drawString(izq, y, linea)
            y -= 4 * mm
        y -= 10 * mm
        c.setStrokeColorRGB(0.3, 0.3, 0.3)
        c.line(izq, y, izq + 80 * mm, y)
        c.line(ancho - izq - 50 * mm, y, ancho - izq, y)
        c.setFont("Helvetica", 8.5)
        c.drawString(izq, y - 4 * mm, "Firma y DNI del apoderado que llena esta ficha")
        c.drawString(ancho - izq - 50 * mm, y - 4 * mm, "Fecha")
        c.setFillColorRGB(0.45, 0.45, 0.45)
        c.drawString(izq, 14 * mm, "Entrega esta hoja al tutor. Tus datos solo se actualizan cuando el tutor la registra.")

    if not alumnos:
        c.setFont("Helvetica", 12)
        c.drawString(20 * mm, alto - 30 * mm, "No hay alumnos en esta sección.")
    c.save()
    return salida.getvalue()


def _recortar(texto: str, fuente: str, tamano: float, ancho: float) -> str:
    while texto and stringWidth(texto, fuente, tamano) > ancho:
        texto = texto[:-2] + "…"
    return texto


@dataclass
class Recibo:
    numero: str
    fecha: datetime  # UTC; se muestra en hora de Lima
    alumno: str
    documento: str
    medio: str
    operacion: str | None
    cajero: str
    lineas: list[tuple[str, str]]  # (detalle, monto con dos decimales)
    total: str
    anulado: str | None = None  # motivo, si se anuló


def recibo(imagen: Imagen, r: Recibo) -> bytes:
    """Recibo interno del colegio (no es comprobante de SUNAT): media hoja A4 con logo y colores del colegio."""
    from app.fechas import LIMA

    salida = BytesIO()
    c = Canvas(salida, pagesize=A4)
    c.setTitle(f"Recibo {r.numero} · {imagen.nombre}")
    ancho, alto = A4
    color = HexColor(imagen.color_primario)
    logo = _logo(imagen)
    izq, util = 20 * mm, ancho - 40 * mm
    y = alto - 20 * mm
    if logo:
        c.drawImage(logo, izq, y - 16 * mm, 16 * mm, 16 * mm, preserveAspectRatio=True, mask="auto")
    x = izq + (20 * mm if logo else 0)
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", _ajustar(imagen.nombre, "Helvetica-Bold", 15, util - 75 * mm))
    c.drawString(x, y - 7 * mm, imagen.nombre)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.setFont("Helvetica", 9)
    c.drawString(x, y - 13 * mm, "Recibo interno de caja (no es comprobante de pago electrónico)")
    # Recuadro con el número.
    c.setStrokeColor(color)
    c.setLineWidth(1.2)
    c.roundRect(ancho - izq - 55 * mm, y - 17 * mm, 55 * mm, 17 * mm, 2.5 * mm)
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(ancho - izq - 27.5 * mm, y - 6.5 * mm, "RECIBO")
    c.setFont("Courier-Bold", 13)
    c.drawCentredString(ancho - izq - 27.5 * mm, y - 13 * mm, r.numero)

    y -= 28 * mm
    c.setFillColorRGB(0.1, 0.1, 0.1)
    local = r.fecha.astimezone(LIMA)
    datos = [("Fecha", local.strftime("%d/%m/%Y %H:%M")), ("Alumno(a)", r.alumno), ("Documento", r.documento),
             ("Medio de pago", r.medio + (f" · Operación {r.operacion}" if r.operacion else "")),
             ("Cajero(a)", r.cajero)]
    for etiqueta, valor in datos:
        c.setFont("Helvetica", 9.5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(izq, y, etiqueta)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(izq + 32 * mm, y, _recortar(valor, "Helvetica-Bold", 10, util - 32 * mm))
        y -= 6 * mm

    y -= 4 * mm
    c.setFillColor(color)
    c.rect(izq, y - 2 * mm, util, 7 * mm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(izq + 2 * mm, y, "Concepto")
    c.drawRightString(ancho - izq - 2 * mm, y, "Importe (S/)")
    y -= 8 * mm
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.5)
    for detalle, monto in r.lineas:
        c.setFont("Helvetica", 10)
        c.drawString(izq + 2 * mm, y, _recortar(detalle, "Helvetica", 10, util - 35 * mm))
        c.drawRightString(ancho - izq - 2 * mm, y, f"{float(monto):,.2f}")
        c.line(izq, y - 2.5 * mm, ancho - izq, y - 2.5 * mm)
        y -= 7 * mm
    c.setFont("Helvetica-Bold", 11.5)
    c.drawString(izq + 2 * mm, y - 1 * mm, "Total")
    c.drawRightString(ancho - izq - 2 * mm, y - 1 * mm, f"S/ {float(r.total):,.2f}")

    if r.anulado:
        c.saveState()
        c.setFillColorRGB(0.8, 0.1, 0.1)
        c.setFont("Helvetica-Bold", 44)
        c.translate(ancho / 2, alto - 95 * mm)
        c.rotate(18)
        c.drawCentredString(0, 0, "ANULADO")
        c.setFont("Helvetica", 10)
        c.drawCentredString(0, -8 * mm, _recortar(f"Motivo: {r.anulado}", "Helvetica", 10, util))
        c.restoreState()
    c.save()
    return salida.getvalue()
