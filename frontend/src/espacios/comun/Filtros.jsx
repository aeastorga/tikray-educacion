import { Search } from 'lucide-react'

// Barra de filtros: un Buscador, selects y, a la derecha, el total ("600 alumnos").
export default function Filtros({ children, total }) {
  return (
    <div className="filtros" role="search">
      <div className="filtros-campos">{children}</div>
      {total != null && <span className="filtros-total tenue">{total}</span>}
    </div>
  )
}

export function Buscador({ valor, cambiar, placeholder, etiqueta }) {
  return (
    <label className="buscador">
      <span className="solo-lectores">{etiqueta || placeholder}</span>
      <Search size={18} aria-hidden="true" />
      <input type="search" value={valor} placeholder={placeholder} onChange={(e) => cambiar(e.target.value)} />
    </label>
  )
}

export function Selector({ valor, cambiar, etiqueta, opciones }) {
  return (
    <label className="selector">
      <span className="solo-lectores">{etiqueta}</span>
      <select value={valor} onChange={(e) => cambiar(e.target.value)} aria-label={etiqueta}>
        {opciones.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  )
}
