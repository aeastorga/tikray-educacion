"""Exportar un reporte (una tabla) a Excel."""

from decimal import Decimal
from io import BytesIO

from fastapi import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def tabla(titulo: str, encabezados: list[str], filas: list[list], nombre: str, color: str = "1F4E79",
          soles: tuple[int, ...] = ()) -> Response:
    """Título en la fila 1, encabezados en la 2 y las filas debajo. `soles`: índices de columnas con montos
    (se guardan como número con dos decimales, no como texto)."""
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31].replace("/", "-")
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(encabezados)
    for celda in ws[2]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=color.lstrip("#"))
    for fila in filas:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in fila])
        for i in soles:
            ws.cell(row=ws.max_row, column=i + 1).number_format = "#,##0.00"
    for i, cab in enumerate(encabezados, 1):
        largo = max([len(str(cab))] + [len(str(f[i - 1])) for f in filas if i - 1 < len(f)])
        ws.column_dimensions[ws.cell(row=2, column=i).column_letter].width = min(50, max(12, largo + 2))
    ws.freeze_panes = "A3"
    buf = BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
