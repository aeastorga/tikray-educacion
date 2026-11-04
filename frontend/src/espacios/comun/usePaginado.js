import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api.js'

// Lista paginada del backend (?pagina=&por_pagina=). `filtros` cambia → vuelve a la página 1.
export default function usePaginado(ruta, filtros = {}, { porPagina: inicial = 25, demora = 250 } = {}) {
  const [pag, setPag] = useState({ pagina: 1, porPagina: inicial })
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const [cargando, setCargando] = useState(true)
  const clave = JSON.stringify(filtros)
  const previa = useRef(clave)
  const vuelta = useRef(0)

  if (previa.current !== clave) {
    previa.current = clave
    if (pag.pagina !== 1) setPag({ ...pag, pagina: 1 })
  }

  const cargar = useCallback(() => {
    const n = ++vuelta.current
    const p = new URLSearchParams({ pagina: pag.pagina, por_pagina: pag.porPagina })
    for (const [k, v] of Object.entries(JSON.parse(clave))) if (v !== '' && v != null && v !== false) p.set(k, v)
    setCargando(true)
    setError(null)
    return api(`${ruta}?${p}`)
      .then((d) => { if (n === vuelta.current) setDatos(d) })
      .catch((e) => { if (n === vuelta.current) setError(e.message) })
      .finally(() => { if (n === vuelta.current) setCargando(false) })
  }, [ruta, clave, pag])

  useEffect(() => {
    const t = setTimeout(cargar, demora)
    return () => clearTimeout(t)
  }, [cargar, demora])

  const paginacion = datos && {
    pagina: datos.pagina, paginas: datos.paginas, total: datos.total, porPagina: datos.por_pagina,
    cambiar: (p) => setPag(p),
  }
  return { datos, error, cargando: cargando && !datos, recargando: cargando, recargar: cargar, paginacion }
}
