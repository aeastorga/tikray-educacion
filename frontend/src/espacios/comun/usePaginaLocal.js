import { useEffect, useState } from 'react'

// Páginas para una lista que ya llegó completa (el día de una sección, el personal). Con 25 filas
// o menos no hace falta paginar y `paginacion` es null.
export default function usePaginaLocal(filas, porPagina = 25) {
  const [pag, setPag] = useState({ pagina: 1, porPagina })
  const total = filas?.length || 0
  const paginas = Math.max(1, Math.ceil(total / pag.porPagina))
  useEffect(() => { if (pag.pagina > paginas) setPag((p) => ({ ...p, pagina: 1 })) }, [pag.pagina, paginas])
  const pagina = Math.min(pag.pagina, paginas)
  const desde = (pagina - 1) * pag.porPagina
  return {
    filas: filas && filas.slice(desde, desde + pag.porPagina),
    paginacion: total > 25 ? { pagina, paginas, total, porPagina: pag.porPagina, cambiar: setPag } : null,
  }
}
