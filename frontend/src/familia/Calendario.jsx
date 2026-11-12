// Calendario escolar en la app de la familia: los eventos que tocan a sus hijos (todo el colegio, su nivel o su
// sección) y los días sin clases. Vista de mes y lista de próximos.
import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../api.js'
import { DetalleDia, ListaProximos, MesCalendario, NavegarMes } from '../espacios/CalendarioMes.jsx'
import { Cargando, Mensaje, Vacio } from '../espacios/comun/index.js'

export default function CalendarioFamilia() {
  const { yo } = useOutletContext()
  const [vista, setVista] = useState('proximos')
  if (yo?.modulos?.calendario === false) return <p className="tenue">El colegio no usa el calendario en la app.</p>
  if (yo && yo.estado !== 'activo') return <p className="tenue">Verá el calendario cuando el colegio apruebe su cuenta.</p>
  return (
    <>
      <div className="saludo"><h1>Calendario</h1>
        <p className="tenue">Actuaciones, reuniones, exámenes y días sin clases de sus hijos.</p>
      </div>
      <div className="pildoras" role="group" aria-label="Vista">
        <button type="button" className="pildora" aria-pressed={vista === 'proximos'} onClick={() => setVista('proximos')}>Próximos</button>
        <button type="button" className="pildora" aria-pressed={vista === 'mes'} onClick={() => setVista('mes')}>Mes</button>
      </div>
      {vista === 'mes' ? <Mes /> : <Proximos />}
    </>
  )
}

function Proximos() {
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { api('/api/familia/calendario/proximos').then(setD).catch((e) => setError(e.message)) }, [])
  if (error) return <Mensaje tipo="error">{error}</Mensaje>
  if (!d) return <Cargando />
  return <ListaProximos eventos={d.eventos} sinClases={d.sin_clases} hijos vacio={{ titulo: 'No hay eventos próximos', texto: 'Cuando el colegio publique una actuación, reunión o día sin clases, aparecerá aquí.' }} />
}

function Mes() {
  const [mes, setMes] = useState(null)
  const [d, setD] = useState(null)
  const [dia, setDia] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => {
    api(`/api/familia/calendario/mes${mes ? `?mes=${mes}` : ''}`).then((r) => { setD(r); if (!mes) setMes(r.mes) })
      .catch((e) => setError(e.message))
  }, [mes])
  useEffect(() => { cargar() }, [cargar])
  if (error) return <Mensaje tipo="error">{error}</Mensaje>
  if (!d) return <Cargando />
  return (
    <section className="tarjeta-app calendario-familia">
      <NavegarMes mes={d.mes} hoy={d.hoy} cambiar={(m) => { setMes(m); setDia(null) }} />
      <MesCalendario mes={d.mes} hoy={d.hoy} eventos={d.eventos} sinClases={d.sin_clases} elegido={dia} elegir={setDia} />
      {dia ? <DetalleDia dia={dia} eventos={d.eventos} sinClases={d.sin_clases} hijos />
        : <p className="tenue">{d.eventos.length || d.sin_clases.length ? 'Toque un día para ver el detalle.' : 'No hay eventos este mes.'}</p>}
    </section>
  )
}
