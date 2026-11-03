// Selector de apariencia: claro, oscuro o automático (lo que diga el equipo). Se guarda en este equipo.
import { Monitor, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { elegirTema, temaGuardado } from './tema.js'
import './apariencia.css'

const OPCIONES = [
  ['claro', 'Claro', Sun],
  ['oscuro', 'Oscuro', Moon],
  ['auto', 'Automático', Monitor],
]

export function Apariencia({ className = '' }) {
  const [tema, setTema] = useState(temaGuardado)
  useEffect(() => {
    const cambio = (e) => setTema(e.detail)
    window.addEventListener('tikray-tema', cambio)
    return () => window.removeEventListener('tikray-tema', cambio)
  }, [])
  return (
    <fieldset className={`apariencia ${className}`}>
      <legend>Apariencia</legend>
      <div className="apariencia-opciones">
        {OPCIONES.map(([valor, texto, Icono]) => (
          <label key={valor} className="apariencia-opcion">
            <input type="radio" name="apariencia" value={valor} checked={tema === valor}
              onChange={() => elegirTema(valor)} />
            <Icono size={16} aria-hidden="true" />
            <span>{texto}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
