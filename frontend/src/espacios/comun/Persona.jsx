import { iniciales } from './texto.js'

export default function Persona({ nombre, detalle }) {
  return (
    <span className="persona">
      <span className="persona-avatar" aria-hidden="true">{iniciales(nombre || '')}</span>
      <span className="persona-texto">
        <b>{nombre}</b>
        {detalle && <span className="tenue persona-detalle">{detalle}</span>}
      </span>
    </span>
  )
}
