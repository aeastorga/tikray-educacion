import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, descargar } from '../api.js'
import Porteria from '../porteria/Porteria.jsx'
import { fechaLima } from '../porteria/reglas.js'
import { CalendarOff, Users } from 'lucide-react'
import { Cifras, Encabezado, Insignia, MenuAcciones, Paginacion, Persona, plural, Tabla, usePaginaLocal } from './comun/index.js'
import './asistencia.css'

const ESTADOS = { presente: 'A tiempo', tarde: 'Tarde', falta: 'Falta', justificada: 'Justificada', licencia: 'Licencia' }
const TONOS = { presente: 'bien', tarde: 'tarde', falta: 'falta', justificada: 'info', licencia: 'info' }
const TIPOS_LICENCIA = { salud: 'Salud', personal: 'Personal', vacaciones: 'Vacaciones', comision: 'Comisión de servicio', maternidad: 'Maternidad / paternidad', otro: 'Otro' }

export default function Asistencia({ yo, marcar, licencias, reglas }) {
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
        {marcar && <Route path="porteria" element={<Porteria yo={yo} />} />}
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

function Estado({ valor, minutos }) {
  if (!valor) return <Insignia tono="neutro">Sin marcar</Insignia>
  return <Insignia tono={TONOS[valor]}>{ESTADOS[valor]}{minutos > 0 ? ` · ${minutos} min` : ''}</Insignia>
}

const numero = (id, titulo, campo = id) => ({ id, titulo, numero: true, alinear: 'derecha', celda: (s) => s[campo] })

function Tardia({ si }) {
  return si ? <span className="segunda-linea marca-tardia" title="Recibida más de 10 minutos después de su hora">registrada después</span> : null
}

function Hora({ valor, tardia }) {
  return <>{valor ? <span className="nowrap">{valor}</span> : <span className="tenue">—</span>}<Tardia si={tardia} /></>
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
  const secciones = usePaginaLocal(dia?.secciones)
  const alumnos = usePaginaLocal(detalle?.alumnos)

  return (
    <>
      <Encabezado titulo="Asistencia de alumnos" descripcion="Toca una sección para ver a cada alumno. Los días no lectivos no tienen faltas."
                  acciones={(
                    <>
                      {dia && !dia.lectivo && <Insignia tono="info">Día no lectivo</Insignia>}
                      <label className="en-linea">Día<input type="date" value={fecha} onChange={(e) => { setFecha(e.target.value); setSeccion(null) }} /></label>
                    </>
                  )} />
      {error && <p className="error">{error}</p>}
      {dia && (
        <Cifras items={[
          { etiqueta: 'A tiempo', valor: dia.totales.presente, tono: 'bien' },
          { etiqueta: 'Tarde', valor: dia.totales.tarde, tono: 'tarde' },
          { etiqueta: 'Falta', valor: dia.totales.falta, tono: 'falta' },
          { etiqueta: 'Justificada', valor: dia.totales.justificada },
          { etiqueta: 'Sin marcar', valor: dia.totales.sin_registro },
        ]} />
      )}
      <Tabla etiqueta="Asistencia por sección" cargando={!dia && !error} filas={secciones.filas} alFila={setSeccion}
             claseFila={(s) => (s.id === seccion?.id ? 'seleccionada' : '')}
             vacio={{ icono: Users, titulo: 'Sin secciones', texto: 'Crea las secciones del año en Padrón.' }}
             columnas={[
               { id: 'seccion', titulo: 'Sección', celda: (s) => s.nombre },
               numero('total', 'Alumnos'), numero('presente', 'A tiempo'), numero('tarde', 'Tarde'), numero('falta', 'Faltas'),
               { ...numero('justificada', 'Justificadas'), ocultarEnCelular: true }, numero('sin_registro', 'Sin marcar'),
             ]} />
      {secciones.paginacion && <Paginacion {...secciones.paginacion} />}
      {seccion && detalle?.alumnos && (
        <section className="detalle-seccion">
          <Encabezado nivel={3} titulo={seccion.nombre} descripcion={plural(detalle.alumnos.length, 'alumno', 'alumnos')}
                      acciones={<button className="boton secundario chico" onClick={() => setSeccion(null)}>Cerrar</button>} />
          <Tabla etiqueta={`Alumnos de ${seccion.nombre}`} filas={alumnos.filas} clave={(a) => a.alumno_id}
                 vacio={{ icono: Users, titulo: 'Sección sin alumnos' }}
                 columnas={[
                   { id: 'alumno', titulo: 'Alumno', celda: (a) => <Persona nombre={a.nombre} /> },
                   { id: 'estado', titulo: 'Estado', nowrap: true, celda: (a) => <Estado valor={a.estado} minutos={a.minutos_tarde} /> },
                   { id: 'entrada', titulo: 'Entrada', numero: true, alinear: 'derecha', celda: (a) => <Hora valor={a.entrada} tardia={a.registrada_despues} /> },
                   { id: 'salida', titulo: 'Salida', numero: true, alinear: 'derecha', celda: (a) => <Hora valor={a.salida} /> },
                 ]} />
          {alumnos.paginacion && <Paginacion {...alumnos.paginacion} />}
        </section>
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

  const personal = usePaginaLocal(dia?.personal)

  async function borrar(l) {
    if (!confirm(`¿Quitar la licencia de ${l.nombre}?`)) return
    try { await api(`/api/asistencia/licencias/${l.id}`, { metodo: 'DELETE' }); recargar(); recargarLicencias() }
    catch (err) { setErrorForm(err.message) }
  }

  return (
    <>
      <Encabezado titulo="Asistencia del personal" descripcion="Solo el personal con turno asignado recibe tardanza y falta automática."
                  acciones={(
                    <>
                      {dia && !dia.lectivo && <Insignia tono="info">Día no lectivo</Insignia>}
                      <label className="en-linea">Día<input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} /></label>
                    </>
                  )} />
      {error && <p className="error">{error}</p>}
      <Tabla etiqueta="Asistencia del personal" cargando={!dia && !error} filas={personal.filas} clave={(p) => p.usuario_id}
             vacio={{ icono: Users, titulo: 'Sin personal registrado', texto: 'Agrégalo en la pestaña Personal.' }}
             columnas={[
               { id: 'persona', titulo: 'Persona', celda: (p) => <Persona nombre={p.nombre} detalle={p.rol} /> },
               { id: 'turno', titulo: 'Turno', celda: (p) => p.turno || <span className="tenue">Sin turno</span> },
               { id: 'estado', titulo: 'Estado', nowrap: true, celda: (p) => <Estado valor={p.estado} minutos={p.minutos_tarde} /> },
               { id: 'entrada', titulo: 'Entrada', numero: true, alinear: 'derecha', celda: (p) => <Hora valor={p.entrada} tardia={p.registrada_despues} /> },
               { id: 'salida', titulo: 'Salida', numero: true, alinear: 'derecha', celda: (p) => <Hora valor={p.salida} /> },
             ]} />
      {personal.paginacion && <Paginacion {...personal.paginacion} />}
      <Mensual ruta="/api/asistencia/personal/mensual.xlsx" nombre="asistencia-personal" />

      <Encabezado nivel={3} titulo="Licencias" descripcion="Los días con licencia no cuentan como falta." />
      <Tabla etiqueta="Licencias" cargando={!lista} filas={lista}
             vacio={{ icono: CalendarOff, titulo: 'No hay licencias registradas', texto: editar ? 'Regístralas con el formulario de abajo.' : null }}
             columnas={[
               { id: 'persona', titulo: 'Persona', celda: (l) => <Persona nombre={l.nombre} detalle={l.motivo} /> },
               { id: 'tipo', titulo: 'Tipo', celda: (l) => <Insignia tono="info">{TIPOS_LICENCIA[l.tipo]}</Insignia> },
               { id: 'desde', titulo: 'Desde', nowrap: true, celda: (l) => fechaCorta(l.desde) },
               { id: 'hasta', titulo: 'Hasta', nowrap: true, celda: (l) => fechaCorta(l.hasta) },
               editar && { id: 'acciones', acciones: true, celda: (l) => (
                 <MenuAcciones etiqueta={l.nombre} opciones={[{ texto: 'Quitar licencia', peligro: true, alHacer: () => borrar(l) }]} />
               ) },
             ].filter(Boolean)} />
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

function fechaCorta(iso) {
  const [a, m, d] = iso.split('-').map(Number)
  return new Date(a, m - 1, d).toLocaleDateString('es-PE', { day: 'numeric', month: 'short', year: 'numeric' }).replace(/\s/g, '\u00A0')
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
