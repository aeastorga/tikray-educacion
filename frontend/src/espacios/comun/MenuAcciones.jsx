import { MoreHorizontal } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

// Un botón principal visible y "Más acciones" con el resto. Las peligrosas, en rojo y al final.
// principal: { texto, alHacer, icono } · opciones: [{ texto, alHacer, peligro, icono }]
export default function MenuAcciones({ principal, opciones = [], etiqueta }) {
  const [abierto, setAbierto] = useState(false)
  const [pos, setPos] = useState(null)
  const boton = useRef(null)
  const lista = useRef(null)
  const normales = opciones.filter((o) => o && !o.peligro)
  const peligrosas = opciones.filter((o) => o && o.peligro)

  const cerrar = useCallback((devolverFoco = true) => {
    setAbierto(false)
    setPos(null)
    if (devolverFoco) boton.current?.focus()
  }, [])

  useLayoutEffect(() => {
    if (!abierto || !boton.current) return
    // Fija respecto de la ventana: así no lo recorta la caja de la tabla.
    const r = boton.current.getBoundingClientRect()
    const alto = lista.current?.offsetHeight || 0
    const abajo = r.bottom + 6 + alto < window.innerHeight
    setPos({ top: abajo ? r.bottom + 6 : Math.max(8, r.top - 6 - alto), right: Math.max(8, window.innerWidth - r.right) })
  }, [abierto])

  // El foco entra al menú cuando ya está ubicado (oculto no se puede enfocar).
  const ubicado = abierto && pos !== null
  useEffect(() => {
    if (ubicado) lista.current?.querySelector('[role="menuitem"]')?.focus()
  }, [ubicado])

  useEffect(() => {
    if (!abierto) return undefined
    const fuera = (e) => {
      if (!lista.current?.contains(e.target) && !boton.current?.contains(e.target)) cerrar(false)
    }
    const salir = () => cerrar(false)
    document.addEventListener('pointerdown', fuera)
    window.addEventListener('resize', salir)
    window.addEventListener('scroll', salir, true)
    return () => {
      document.removeEventListener('pointerdown', fuera)
      window.removeEventListener('resize', salir)
      window.removeEventListener('scroll', salir, true)
    }
  }, [abierto, cerrar])

  function teclas(e) {
    const items = [...lista.current.querySelectorAll('[role="menuitem"]')]
    const i = items.indexOf(document.activeElement)
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cerrar() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length]?.focus() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus() }
    else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus() }
    else if (e.key === 'End') { e.preventDefault(); items[items.length - 1]?.focus() }
    else if (e.key === 'Tab') cerrar(false)
  }

  function elegir(o) {
    cerrar()
    o.alHacer()
  }

  const item = (o) => {
    const Icono = o.icono
    return (
      <button key={o.texto} type="button" role="menuitem" tabIndex={-1} className={o.peligro ? 'peligro' : undefined}
              onClick={() => elegir(o)}>
        {Icono && <Icono size={16} aria-hidden="true" />}{o.texto}
      </button>
    )
  }

  const Icono = principal?.icono
  return (
    <div className="menu-acciones">
      {principal && (
        <button type="button" className="boton secundario chico" onClick={principal.alHacer} disabled={principal.deshabilitado}>
          {Icono && <Icono size={16} aria-hidden="true" />}{principal.texto}
        </button>
      )}
      {normales.length + peligrosas.length > 0 && (
        <button ref={boton} type="button" className="boton-icono chico" aria-label={etiqueta ? `Más acciones: ${etiqueta}` : 'Más acciones'}
                aria-haspopup="menu" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>
          <MoreHorizontal size={18} aria-hidden="true" />
        </button>
      )}
      {abierto && (
        <div ref={lista} className="menu-acciones-lista" role="menu" aria-label="Más acciones" onKeyDown={teclas}
             style={pos ? { top: pos.top, right: pos.right } : { visibility: 'hidden' }}>
          {normales.map(item)}
          {normales.length > 0 && peligrosas.length > 0 && <hr role="separator" />}
          {peligrosas.map(item)}
        </div>
      )}
    </div>
  )
}
