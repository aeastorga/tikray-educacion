// Ventanas propias en lugar de las del navegador (la ventanita gris de confirmar o escribir): siguen el diseño y el tema oscuro.
//
//   const { confirmar, pedirMotivo } = useConfirmar()
//   if (!await confirmar({ titulo: 'Bloquear acceso', texto: '…', accion: 'Bloquear', peligro: true })) return
//   const motivo = await pedirMotivo({ titulo: 'Anular pago', etiqueta: 'Motivo', accion: 'Anular', peligro: true,
//                                      minimo: 3, maximo: 200 })   // null si cancela
//
// `peligro`: la acción no se puede deshacer (bloquear, borrar, anular…): el botón principal va en rojo.
// En PC la ventana va centrada (unos 440 px); en celular (hasta 600 px) sube desde abajo, a todo el ancho.
// Escape o "Cancelar" cierran sin hacer nada; un clic fuera también, salvo que ya se haya escrito un motivo.
// El foco entra al primer control, no sale con Tab y vuelve al botón que la abrió.
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import './dialogo.css'

const ENFOCABLES = 'input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), '
  + '[href], [tabindex]:not([tabindex="-1"])'

// La ventana base: fondo oscurecido, foco atrapado, Escape y clic fuera. También la usan las ventanas con
// formulario (Plataforma).
export function Ventana({ titulo, mostrarTitulo = true, rol = 'dialog', cerrar, cerrarFuera = () => true,
  ancha = false, describe, children }) {
  const caja = useRef(null)
  const idTitulo = useId()
  const cerrarRef = useRef(cerrar)
  cerrarRef.current = cerrar

  useEffect(() => {
    const antes = document.activeElement
    const primero = caja.current?.querySelector(ENFOCABLES)
    ;(primero || caja.current)?.focus()
    const desplazamiento = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = desplazamiento
      if (antes && document.contains(antes)) antes.focus()
    }
  }, [])

  function teclas(e) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      cerrarRef.current()
      return
    }
    if (e.key !== 'Tab') return
    const lista = [...caja.current.querySelectorAll(ENFOCABLES)]
    if (!lista.length) return
    const [primero, ultimo] = [lista[0], lista[lista.length - 1]]
    if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus() }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus() }
  }

  return createPortal(
    <div className="ventana-fondo" onMouseDown={(e) => { if (e.target === e.currentTarget && cerrarFuera()) cerrar() }}>
      <div ref={caja} className={`ventana${ancha ? ' ancha' : ''}`} role={rol} aria-modal="true" tabIndex={-1}
           onKeyDown={teclas} aria-labelledby={mostrarTitulo ? idTitulo : undefined}
           aria-label={mostrarTitulo ? undefined : titulo} aria-describedby={describe}>
        {mostrarTitulo && <h2 id={idTitulo} className="ventana-titulo">{titulo}</h2>}
        {children}
      </div>
    </div>,
    document.body,
  )
}

const Contexto = createContext(null)

export function ProveedorDialogos({ children }) {
  const [pedido, setPedido] = useState(null)
  const abierto = useRef(false)

  const abrir = useCallback((tipo, opciones) => new Promise((resolver) => {
    const nada = tipo === 'motivo' ? null : false
    if (abierto.current) { resolver(nada); return } // ya hay una abierta: no se abre otra
    abierto.current = true
    setPedido({ tipo, opciones, resolver })
  }), [])

  const api = useMemo(() => ({
    confirmar: (opciones) => abrir('confirmar', opciones),
    pedirMotivo: (opciones) => abrir('motivo', opciones),
  }), [abrir])

  function cerrar(valor) {
    pedido?.resolver(valor)
    abierto.current = false
    setPedido(null)
  }

  return (
    <Contexto.Provider value={api}>
      {children}
      {pedido && <Pedido tipo={pedido.tipo} o={pedido.opciones} cerrar={cerrar} />}
    </Contexto.Provider>
  )
}

export function useConfirmar() {
  const api = useContext(Contexto)
  if (!api) throw new Error('useConfirmar necesita <ProveedorDialogos>')
  return api
}

function Pedido({ tipo, o, cerrar }) {
  const [motivo, setMotivo] = useState('')
  const listo = useRef(false) // un solo envío aunque hagan doble clic
  const idTexto = useId()
  const esMotivo = tipo === 'motivo'
  const minimo = o.minimo ?? 1
  const maximo = o.maximo ?? 200
  const limpio = motivo.trim()
  const valido = !esMotivo || limpio.length >= minimo

  function terminar(valor) {
    if (listo.current) return
    listo.current = true
    cerrar(valor)
  }
  function aceptar(e) {
    e.preventDefault()
    if (valido) terminar(esMotivo ? limpio : true)
  }
  const cancelar = () => terminar(esMotivo ? null : false)

  return (
    <Ventana titulo={o.titulo} rol={esMotivo ? 'dialog' : 'alertdialog'} cerrar={cancelar}
             cerrarFuera={() => !limpio} describe={o.texto ? idTexto : undefined}>
      <form className="ventana-forma" onSubmit={aceptar}>
        {o.texto && <p id={idTexto} className="ventana-texto">{o.texto}</p>}
        {esMotivo && (
          <label className="ventana-campo">
            {o.etiqueta || 'Motivo'}
            <textarea required rows={3} minLength={minimo} maxLength={maximo} value={motivo}
                      placeholder={o.ejemplo} onChange={(e) => setMotivo(e.target.value)} />
            <small className="tenue">
              {minimo > 1 && limpio.length < minimo ? `Al menos ${minimo} caracteres · ` : ''}{motivo.length}/{maximo}
            </small>
          </label>
        )}
        <div className="ventana-botones">
          <button type="button" className="boton secundario" onClick={cancelar}>Cancelar</button>
          <button type="submit" className={`boton${o.peligro ? ' peligro' : ''}`} disabled={!valido}>{o.accion}</button>
        </div>
      </form>
    </Ventana>
  )
}
