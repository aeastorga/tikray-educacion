"""PDF de carnets (con QR) y de cartas de acceso del personal."""

from dataclasses import dataclass
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
