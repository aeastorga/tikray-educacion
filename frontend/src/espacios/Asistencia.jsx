import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, descargar } from '../api.js'
import Porteria from '../porteria/Porteria.jsx'
import { fechaLima } from '../porteria/reglas.js'
import './asistencia.css'

const ESTADOS = { presente: 'Presente', tarde: 'Tarde', falta: 'Falta', licencia: 'Licencia' }
const TIPOS_LICENCIA = { salud: 'Salud', personal: 'Personal', vacaciones: 'Vacaciones', comision: 'Comisión de servicio', maternidad: 'Maternidad / paternidad', otro: 'Otro' }

export default function Asistencia({ marcar, licencias, reglas }) {
  return (
    <section>
      <nav className="subpestanas">
        {marcar && <NavLink to="/panel/asistencia/porteria">Portería</NavLink>}
        <NavLink to="/panel/asistencia" end>Alumnos</NavLink>
        <NavLink to="/panel/asistencia/personal">Personal</NavLink>
        {reglas && <NavLink to="/panel/asistencia/reglas">Reglas</NavLink>}
      </nav>
      <Routes>
        <Route index element={<Alumnos />} />
        {marcar && <Route path="porteria" element={<Porteria />} />}
        <Route path="personal" element={<Personal licencias={licencias} />} />
        {reglas && <Route path="reglas" element={<Reglas />} />}
      </Routes>
    </section>
  )
}

function useDia(ruta) {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => {
    setError(null)
    if (!ruta) return setDatos(null)
    return api(ruta).then(setDatos).catch((e) => setError(e.message))
  }, [ruta])
  useEffect(() => { cargar() }, [cargar])
  return [datos, error, cargar]
}

function Estado({ valor }) {
  return valor ? <span className={`estado ${valor}`}>{ESTADOS[valor]}</span> : <span className="tenue">Sin registro</span>
}

function Mensual({ ruta, nombre }) {
  const hoy = fechaLima(new Date())
  const [mes, setMes] = useState(hoy.slice(0, 7))
  const [error, setError] = useState(null)
  async function bajar() {
    setError(null)
    const [a, m] = mes.split('-')
    try { await descargar(`${ruta}${ruta.includes('?') ? '&' : '?'}anio=${a}&mes=${Number(m)}`, `${nombre}-${mes}.xlsx`) }
    catch (e) { setError(e.message) }
  }
  return (
    <div className="fila-form">
      <label>Registro del mes<input type="month" value={mes} onChange={(e) => setMes(e.target.value)} /></label>
      <button className="boton secundario" onClick={bajar}>Descargar Excel</button>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function Alumnos() {
  const [fecha, setFecha] = useState(fechaLima(new Date()))
  const [seccion, setSeccion] = useState(null)
  const [dia, error] = useDia(`/api/asistencia/dia?fecha=${fecha}`)
  const [detalle] = useDia(seccion ? `/api/asistencia/dia?fecha=${fecha}&seccion_id=${seccion.id}` : null)

  return (
    <>
      <div className="fila-form sin-margen">
        <label>Día<input type="date" value={fecha} onChange={(e) => { setFecha(e.target.value); setSeccion(null) }} /></label>
        {dia && !dia.lectivo && <span className="aviso-chico">Día no lectivo</span>}
      </div>
      {error && <p className="error">{error}</p>}
      {dia && (
        <>
          <div className="totales">
            {['presente', 'tarde', 'falta', 'sin_registro'].map((k) => (
              <div key={k} className={`total ${k}`}><b>{dia.totales[k]}</b><span>{ESTADOS[k] || 'Sin registro'}</span></div>
            ))}
          </div>
          <table>
            <thead><tr><th>Sección</th><th>Alumnos</th><th>Presentes</th><th>Tarde</th><th>Faltas</th><th>Sin registro</th></tr></thead>
            <tbody>
              {dia.secciones.map((s) => (
                <tr key={s.id} className="clic" onClick={() => setSeccion(s)}>
                  <td>{s.nombre}</td><td>{s.total}</td><td>{s.presente}</td><td>{s.tarde}</td><td>{s.falta}</td><td>{s.sin_registro}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {seccion && detalle?.alumnos && (
        <>
          <h3>{seccion.nombre} <button className="enlace" onClick={() => setSeccion(null)}>Cerrar</button></h3>
          <table>
            <thead><tr><th>Alumno</th><th>Estado</th><th>Entrada</th><th>Salida</th></tr></thead>
            <tbody>
              {detalle.alumnos.map((a) => (
                <tr key={a.alumno_id}>
                  <td>{a.nombre}</td>
                  <td><Estado valor={a.estado} />{a.minutos_tarde > 0 && <span className="tenue"> {a.minutos_tarde} min</span>}</td>
                  <td>{a.entrada || '—'}</td><td>{a.salida || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <Mensual ruta={`/api/asistencia/mensual.xlsx${seccion ? `?seccion_id=${seccion.id}` : ''}`} nombre="asistencia" />
    </>
  )
}

function Personal({ licencias: editar }) {
  const [fecha, setFecha] = useState(fechaLima(new Date()))
  const [dia, error, recargar] = useDia(`/api/asistencia/personal/dia?fecha=${fecha}`)
  const [lista, , recargarLicencias] = useDia('/api/asistencia/licencias')
  const vacio = { usuario_id: '', tipo: 'salud', desde: fecha, hasta: fecha, motivo: '' }
  const [form, setForm] = useState(vacio)
  const [errorForm, setErrorForm] = useState(null)

  async function crear(e) {
    e.preventDefault()
    setErrorForm(null)
    try {
      await api('/api/asistencia/licencias', { metodo: 'POST', datos: { ...form, usuario_id: Number(form.usuario_id) } })
      setForm(vacio)
      recargar()
      recargarLicencias()
    } catch (err) { setErrorForm(err.message) }
  }

  async function borrar(l) {
    if (!confirm(`¿Quitar la licencia de ${l.nombre}?`)) return
    try { await api(`/api/asistencia/licencias/${l.id}`, { metodo: 'DELETE' }); recargar(); recargarLicencias() }
    catch (err) { setErrorForm(err.message) }
  }

  return (
    <>
      <div className="fila-form sin-margen">
        <label>Día<input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} /></label>
        {dia && !dia.lectivo && <span className="aviso-chico">Día no lectivo</span>}
      </div>
      {error && <p className="error">{error}</p>}
      {dia && (
        <table>
          <thead><tr><th>Persona</th><th>Rol</th><th>Turno</th><th>Estado</th><th>Entrada</th><th>Salida</th></tr></thead>
          <tbody>
            {dia.personal.map((p) => (
              <tr key={p.usuario_id}>
                <td>{p.nombre}</td><td>{p.rol}</td><td>{p.turno || <span className="tenue">Sin turno</span>}</td>
                <td><Estado valor={p.estado} />{p.minutos_tarde > 0 && <span className="tenue"> {p.minutos_tarde} min</span>}</td>
                <td>{p.entrada || '—'}</td><td>{p.salida || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="tenue">Solo el personal con turno asignado (pestaña Personal) recibe tardanza y falta automática.</p>
      <Mensual ruta="/api/asistencia/personal/mensual.xlsx" nombre="asistencia-personal" />

      <h3>Licencias</h3>
      {lista && lista.length === 0 && <p className="tenue">No hay licencias registradas.</p>}
      {lista && lista.length > 0 && (
        <table>
          <thead><tr><th>Persona</th><th>Tipo</th><th>Desde</th><th>Hasta</th><th>Motivo</th>{editar && <th />}</tr></thead>
          <tbody>
            {lista.map((l) => (
              <tr key={l.id}>
                <td>{l.nombre}</td><td>{TIPOS_LICENCIA[l.tipo]}</td><td>{l.desde}</td><td>{l.hasta}</td><td>{l.motivo || ''}</td>
                {editar && <td><button className="enlace" onClick={() => borrar(l)}>Quitar</button></td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editar && dia && (
        <form className="fila-form" onSubmit={crear}>
          <select required value={form.usuario_id} onChange={(e) => setForm({ ...form, usuario_id: e.target.value })}>
            <option value="">Persona…</option>
            {dia.personal.map((p) => <option key={p.usuario_id} value={p.usuario_id}>{p.nombre}</option>)}
          </select>
          <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
            {Object.entries(TIPOS_LICENCIA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label>Desde<input type="date" required value={form.desde} onChange={(e) => setForm({ ...form, desde: e.target.value })} /></label>
          <label>Hasta<input type="date" required value={form.hasta} min={form.desde} onChange={(e) => setForm({ ...form, hasta: e.target.value })} /></label>
          <input placeholder="Motivo (opcional)" maxLength={200} value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} />
          <button className="boton">Registrar licencia</button>
          {errorForm && <p className="error">{errorForm}</p>}
        </form>
      )}
    </>
  )
}

function Reglas() {
  const [form, setForm] = useState(null)
  const [mensaje, setMensaje] = useState(null)
  useEffect(() => { api('/api/asistencia/configuracion').then(setForm) }, [])

  async function guardar(e) {
    e.preventDefault()
    try {
      setForm(await api('/api/asistencia/configuracion', { metodo: 'PUT', datos: {
        minutos_duplicado: Number(form.minutos_duplicado), minutos_corte_falta: Number(form.minutos_corte_falta) } }))
      setMensaje('Reglas guardadas')
    } catch (err) { setMensaje(err.message) }
  }

  if (!form) return null
  return (
    <form className="tarjeta ancho" onSubmit={guardar}>
      <label>Doble marcación: lecturas de la misma persona con menos de estos minutos cuentan como una
        <input type="number" min={1} max={120} value={form.minutos_duplicado}
               onChange={(e) => setForm({ ...form, minutos_duplicado: e.target.value })} />
      </label>
      <label>Falta automática: minutos después de la hora de entrada del turno en que se marca falta a quien no llegó
        <input type="number" min={15} max={600} value={form.minutos_corte_falta}
               onChange={(e) => setForm({ ...form, minutos_corte_falta: e.target.value })} />
      </label>
      <p className="tenue">La hora de entrada y la tolerancia de cada turno se configuran en Padrón → Niveles y turnos.
        Las faltas automáticas solo se marcan en días lectivos (Padrón → Calendario).</p>
      <div className="acciones">
        <button className="boton">Guardar</button>
        {mensaje && <span className="tenue">{mensaje}</span>}
      </div>
    </form>
  )
}
