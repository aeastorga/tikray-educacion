import { ChevronLeft, ChevronRight } from 'lucide-react'

export const POR_PAGINA = [25, 50, 100]

// "1–25 de 600", Anterior / Siguiente, número de página y cuántos por página.
export default function Paginacion({ pagina, paginas, total, porPagina, cambiar }) {
  if (!total) return null
  const desde = (pagina - 1) * porPagina + 1
  const hasta = Math.min(total, pagina * porPagina)
  return (
    <nav className="paginacion" aria-label="Páginas">
      <span className="paginacion-rango">{desde.toLocaleString('es-PE')}–{hasta.toLocaleString('es-PE')} de {total.toLocaleString('es-PE')}</span>
      <div className="paginacion-control">
        <label className="paginacion-tamano">
          <span className="tenue">Por página</span>
          <select value={porPagina} onChange={(e) => cambiar({ pagina: 1, porPagina: Number(e.target.value) })}>
            {POR_PAGINA.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button type="button" className="boton-icono" aria-label="Página anterior" disabled={pagina <= 1}
                onClick={() => cambiar({ pagina: pagina - 1, porPagina })}>
          <ChevronLeft size={18} aria-hidden="true" />
        </button>
        <span className="paginacion-numero" aria-live="polite">Página {pagina} de {paginas}</span>
        <button type="button" className="boton-icono" aria-label="Página siguiente" disabled={pagina >= paginas}
                onClick={() => cambiar({ pagina: pagina + 1, porPagina })}>
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      </div>
    </nav>
  )
}
