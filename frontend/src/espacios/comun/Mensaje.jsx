// Un solo diseño para "Guardado", los errores del servidor y "sin conexión" en todas las pantallas, y uno para
// "Cargando…" (con alto mínimo, para que la pantalla no salte al terminar de cargar).
//
//   <Mensaje tipo="ok">Cambios guardados</Mensaje>
//   <Mensaje tipo="error">{error}</Mensaje>
//   <Mensaje tipo="sin-conexion">Sin internet: se guardan en este celular</Mensaje>
import { CircleAlert, CircleCheck, LoaderCircle, WifiOff } from 'lucide-react'
import './mensaje.css'

const ICONO = { ok: CircleCheck, error: CircleAlert, 'sin-conexion': WifiOff }

export function Mensaje({ tipo = 'ok', children, className = '' }) {
  if (children === null || children === undefined || children === false || children === '') return null
  const Icono = ICONO[tipo] || CircleCheck
  return (
    <p className={`mensaje mensaje-${tipo} ${className}`.trim()} role={tipo === 'error' ? 'alert' : 'status'}>
      <Icono size={18} aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

export function Cargando({ texto = 'Cargando…' }) {
  return (
    <p className="cargando" role="status">
      <LoaderCircle size={18} aria-hidden="true" />
      <span>{texto}</span>
    </p>
  )
}
