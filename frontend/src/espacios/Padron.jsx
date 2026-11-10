import { ArrowLeft, CalendarX2, FileSpreadsheet, Layers, UserPlus, Users } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom'
import RecojoAlumno from './RecojoAlumno.jsx'
import { api, descargar, guardarArchivo } from '../api.js'
import {
  Buscador, documento, Encabezado, Filtros, Insignia, MenuAcciones, Paginacion, Persona, plural, Selector, Tabla,
  usePaginado,
} from './comun/index.js'

const DIAS = [['1', 'Lu'], ['2', 'Ma'], ['3', 'Mi'], ['4', 'Ju'], ['5', 'Vi'], ['6', 'Sá'], ['7', 'Do']]
const TIPOS_DOC = ['DNI', 'CE', 'PAS', 'OTRO']

export default function Padron({ editar, recojo }) {
  const [anios, cargarAnios] = useCarga('/api/padron/anios')
  const sinAnio = anios !== null && !anios.some((a) => a.activo)
  const necesitaAnio = (el) => (sinAnio ? <Empezar editar={editar} /> : el)
  return (
    <section>
      <nav className="subpestanas">
        <NavLink to="/panel/padron" end>Alumnos</NavLink>
        <NavLink to="/panel/padron/secciones">Secciones</NavLink>
        <NavLink to="/panel/padron/estructura">Niveles y turnos</NavLink>
        <NavLink to="/panel/padron/calendario">Calendario</NavLink>
        <NavLink to="/panel/padron/anios">Año escolar</NavLink>
        {editar && <NavLink to="/panel/padron/importar">Importar Excel</NavLink>}
      </nav>
      <Routes>
        <Route index element={necesitaAnio(<Alumnos editar={editar} recojo={recojo} />)} />
        <Route path="secciones" element={necesitaAnio(<Secciones editar={editar} />)} />
        <Route path="estructura" element={<Estructura editar={editar} />} />
        <Route path="calendario" element={necesitaAnio(<Calendario editar={editar} />)} />
        <Route path="anios" element={<Anios editar={editar} alCambiar={cargarAnios} />} />
        <Route path="importar" element={necesitaAnio(<Importar />)} />
      </Routes>
    </section>
  )
}

function Empezar({ editar }) {
  return (
    <div className="tarjeta ancho">
      <h2>Para empezar</h2>
      {editar ? (
        <ol className="pasos">
          <li><NavLink to="/panel/padron/anios">Crea el año escolar</NavLink> con sus fechas y días de clase.</li>
          <li>Define los <NavLink to="/panel/padron/estructura">niveles, grados y turnos</NavLink>.</li>
          <li>Crea las secciones del año.</li>
          <li>Carga los alumnos uno por uno o desde Excel.</li>
        </ol>
      ) : <p>Todavía no hay un año escolar activo. Pídele a dirección que lo configure.</p>}
    </div>
  )
}

function useCarga(ruta) {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => {
    setError(null)
    return api(ruta).then(setDatos).catch((e) => setError(e.message))
  }, [ruta])
  useEffect(() => { cargar() }, [cargar])
  return [datos, cargar, error, setError]
}

function MensajeError({ texto }) {
  return texto ? <p className="error">{texto}</p> : null
}

// --- Año escolar ---------------------------------------------------------------

function Anios({ editar, alCambiar }) {
  const [anios, cargarPropio, error, setError] = useCarga('/api/padron/anios')
  const cargar = () => { cargarPropio(); alCambiar() }
  const vacio = { anio: new Date().getFullYear(), inicio: '', fin: '', dias_semana: '12345' }
  const [form, setForm] = useState(vacio)

  async function enviar(e) {
    e.preventDefault()
    try {
      if (form.id) await api(`/api/padron/anios/${form.id}`, { metodo: 'PUT', datos: form })
      else await api('/api/padron/anios', { metodo: 'POST', datos: form })
      setForm(vacio)
      cargar()
    } catch (err) { setError(err.message) }
  }

  const alternarDia = (d) => setForm({
    ...form,
    dias_semana: DIAS.map(([k]) => k).filter((k) => (k === d) !== form.dias_semana.includes(k)).join(''),
  })

  return (
    <>
      <Encabezado titulo="Año escolar" descripcion="Fechas y días de clase. Solo un año está activo a la vez." />
      <Tabla etiqueta="Años escolares" cargando={!anios && !error} filas={anios || []}
             vacio={{ icono: CalendarX2, titulo: 'Todavía no hay años escolares', texto: editar ? 'Crea el primero con el formulario de abajo.' : null }}
             columnas={[
               { id: 'anio', titulo: 'Año', celda: (a) => a.anio },
               { id: 'inicio', titulo: 'Inicio', nowrap: true, celda: (a) => fecha(a.inicio) },
               { id: 'fin', titulo: 'Fin', nowrap: true, celda: (a) => fecha(a.fin) },
               { id: 'dias', titulo: 'Días de clase', celda: (a) => DIAS.filter(([k]) => a.dias_semana.includes(k)).map(([, v]) => v).join(' ') },
               { id: 'estado', titulo: 'Estado', celda: (a) => <Insignia tono={a.activo ? 'bien' : 'neutro'}>{a.activo ? 'Activo' : 'Inactivo'}</Insignia> },
               editar && { id: 'acciones', acciones: true, celda: (a) => (
                 <MenuAcciones etiqueta={`Año ${a.anio}`} principal={{ texto: 'Editar', alHacer: () => setForm(a) }}
                               opciones={a.activo ? [] : [{ texto: 'Activar', alHacer: () => api(`/api/padron/anios/${a.id}/activar`, { metodo: 'POST' }).then(cargar) }]} />
               ) },
             ].filter(Boolean)} />
      {editar && (
        <form className="fila-form" onSubmit={enviar}>
          <label>Año<input type="number" value={form.anio} onChange={(e) => setForm({ ...form, anio: Number(e.target.value) })} required /></label>
          <label>Inicio<input type="date" value={form.inicio} onChange={(e) => setForm({ ...form, inicio: e.target.value })} required /></label>
          <label>Fin<input type="date" value={form.fin} onChange={(e) => setForm({ ...form, fin: e.target.value })} required /></label>
          <fieldset className="dias">
            <legend>Días de clase</legend>
            {DIAS.map(([k, v]) => (
              <label key={k} className="check"><input type="checkbox" checked={form.dias_semana.includes(k)} onChange={() => alternarDia(k)} />{v}</label>
            ))}
          </fieldset>
          <button className="boton">{form.id ? 'Guardar' : 'Crear año'}</button>
          {form.id && <button type="button" className="enlace" onClick={() => setForm(vacio)}>Cancelar</button>}
        </form>
      )}
      <MensajeError texto={error} />
    </>
  )
}

// --- Niveles, grados y turnos -------------------------------------------------

function Estructura({ editar }) {
  const [est, cargar, error, setError] = useCarga('/api/padron/estructura')
  const [nivel, setNivel] = useState('')
  const [grado, setGrado] = useState({ nivel_id: '', nombre: '' })
  const [turno, setTurno] = useState({ nombre: '', hora_entrada: '07:45', tolerancia_minutos: 10, hora_salida: '13:00' })

  const accion = (fn) => async (e) => {
    e?.preventDefault?.()
    setError(null)
    try { await fn(); cargar() } catch (err) { setError(err.message) }
  }

  if (!est) return <MensajeError texto={error} />
  return (
    <>
      <Encabezado titulo="Niveles y grados" descripcion="Cada sección pertenece a un grado de un nivel." />
      {est.niveles.map((n) => (
        <div key={n.id} className="bloque">
          <b>{n.nombre}</b>{' '}
          {n.grados.map((g) => (
            <span key={g.id} className="chip">{g.nombre}
              {editar && <button className="enlace" title="Borrar grado" onClick={accion(() => api(`/api/padron/grados/${g.id}`, { metodo: 'DELETE' }))}>×</button>}
            </span>
          ))}
          {editar && n.grados.length === 0 &&
            <button className="enlace" onClick={accion(() => api(`/api/padron/niveles/${n.id}`, { metodo: 'DELETE' }))}>Borrar nivel</button>}
        </div>
      ))}
      {editar && (
        <>
          <form className="fila-form" onSubmit={accion(async () => {
            await api('/api/padron/niveles', { metodo: 'POST', datos: { nombre: nivel, orden: est.niveles.length + 1 } })
            setNivel('')
          })}>
            <input placeholder="Nuevo nivel (Inicial, Primaria…)" value={nivel} onChange={(e) => setNivel(e.target.value)} required />
            <button className="boton">Agregar nivel</button>
          </form>
          <form className="fila-form" onSubmit={accion(async () => {
            const n = est.niveles.find((x) => x.id === Number(grado.nivel_id))
            await api('/api/padron/grados', { metodo: 'POST', datos: { ...grado, nivel_id: Number(grado.nivel_id), orden: (n?.grados.length || 0) + 1 } })
            setGrado({ ...grado, nombre: '' })
          })}>
            <select value={grado.nivel_id} onChange={(e) => setGrado({ ...grado, nivel_id: e.target.value })} required>
              <option value="">Nivel…</option>
              {est.niveles.map((n) => <option key={n.id} value={n.id}>{n.nombre}</option>)}
            </select>
            <input placeholder="Grado (1°, 3 años…)" value={grado.nombre} onChange={(e) => setGrado({ ...grado, nombre: e.target.value })} required />
            <button className="boton">Agregar grado</button>
          </form>
        </>
      )}

      <Encabezado titulo="Turnos" descripcion="La tardanza se cuenta desde la hora de entrada más la tolerancia." />
      <Tabla etiqueta="Turnos" filas={est.turnos}
             vacio={{ icono: CalendarX2, titulo: 'Sin turnos', texto: editar ? 'Agrega el primero con el formulario de abajo.' : null }}
             columnas={[
               { id: 'turno', titulo: 'Turno', celda: (t) => t.nombre },
               { id: 'entrada', titulo: 'Entrada', numero: true, alinear: 'derecha', celda: (t) => t.hora_entrada },
               { id: 'tolerancia', titulo: 'Tolerancia', numero: true, alinear: 'derecha', celda: (t) => `${t.tolerancia_minutos} min` },
               { id: 'salida', titulo: 'Salida', numero: true, alinear: 'derecha', celda: (t) => t.hora_salida },
               editar && { id: 'acciones', acciones: true, celda: (t) => (
                 <MenuAcciones etiqueta={`Turno ${t.nombre}`}
                               opciones={[{ texto: 'Borrar', peligro: true, alHacer: accion(() => api(`/api/padron/turnos/${t.id}`, { metodo: 'DELETE' })) }]} />
               ) },
             ].filter(Boolean)} />
      {editar && (
        <form className="fila-form" onSubmit={accion(async () => {
          await api('/api/padron/turnos', { metodo: 'POST', datos: { ...turno, tolerancia_minutos: Number(turno.tolerancia_minutos) } })
          setTurno({ ...turno, nombre: '' })
        })}>
          <input placeholder="Nombre (Mañana, Tarde…)" value={turno.nombre} onChange={(e) => setTurno({ ...turno, nombre: e.target.value })} required />
          <label>Entrada<input type="time" value={turno.hora_entrada} onChange={(e) => setTurno({ ...turno, hora_entrada: e.target.value })} required /></label>
          <label>Tolerancia (min)<input type="number" min="0" max="120" value={turno.tolerancia_minutos} onChange={(e) => setTurno({ ...turno, tolerancia_minutos: e.target.value })} /></label>
          <label>Salida<input type="time" value={turno.hora_salida} onChange={(e) => setTurno({ ...turno, hora_salida: e.target.value })} required /></label>
          <button className="boton">Agregar turno</button>
        </form>
      )}
      <MensajeError texto={error} />
    </>
  )
}

// --- Secciones ----------------------------------------------------------------

function Secciones({ editar }) {
  const [secciones, cargar, error, setError] = useCarga('/api/padron/secciones')
  const [est] = useCarga('/api/padron/estructura')
  const [form, setForm] = useState({ grado_id: '', turno_id: '', nombre: '' })

  async function crear(e) {
    e.preventDefault()
    setError(null)
    try {
      await api('/api/padron/secciones', { metodo: 'POST', datos: { ...form, grado_id: Number(form.grado_id), turno_id: Number(form.turno_id) } })
      setForm({ ...form, nombre: '' })
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function borrar(s) {
    if (!confirm(`¿Borrar la sección ${s.etiqueta}?`)) return
    try { await api(`/api/padron/secciones/${s.id}`, { metodo: 'DELETE' }); cargar() } catch (err) { setError(err.message) }
  }

  async function carnets(s) {
    try { await descargar(`/api/padron/carnets?seccion_id=${s.id}`, `carnets-${s.etiqueta}.pdf`) } catch (err) { setError(err.message) }
  }

  return (
    <>
      <Encabezado titulo="Secciones del año" descripcion="Cada sección con su turno. Desde aquí se imprimen los carnets QR." />
      <Tabla etiqueta="Secciones" cargando={!secciones && !error} filas={secciones || []}
             vacio={{ icono: Layers, titulo: 'Todavía no hay secciones', texto: editar ? 'Agrega la primera con el formulario de abajo.' : null }}
             columnas={[
               { id: 'seccion', titulo: 'Sección', celda: (s) => s.etiqueta },
               { id: 'turno', titulo: 'Turno', celda: (s) => s.turno },
               { id: 'alumnos', titulo: 'Alumnos', numero: true, alinear: 'derecha', celda: (s) => s.alumnos },
               { id: 'acciones', acciones: true, celda: (s) => (
                 <MenuAcciones etiqueta={s.etiqueta}
                               principal={s.alumnos > 0 ? { texto: 'Carnets PDF', alHacer: () => carnets(s) } : null}
                               opciones={editar ? [{ texto: 'Borrar', peligro: true, alHacer: () => borrar(s) }] : []} />
               ) },
             ]} />
      {editar && est && (
        <form className="fila-form" onSubmit={crear}>
          <select value={form.grado_id} onChange={(e) => setForm({ ...form, grado_id: e.target.value })} required>
            <option value="">Grado…</option>
            {est.niveles.map((n) => (
              <optgroup key={n.id} label={n.nombre}>
                {n.grados.map((g) => <option key={g.id} value={g.id}>{n.nombre} · {g.nombre}</option>)}
              </optgroup>
            ))}
          </select>
          <select value={form.turno_id} onChange={(e) => setForm({ ...form, turno_id: e.target.value })} required>
            <option value="">Turno…</option>
            {est.turnos.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
          <input placeholder="Sección (A, B…)" value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} required />
          <button className="boton">Agregar sección</button>
        </form>
      )}
      <MensajeError texto={error} />
    </>
  )
}

// --- Calendario -----------------------------------------------------------------

function Calendario({ editar }) {
  const [dias, cargar, error, setError] = useCarga('/api/padron/dias-no-lectivos')
  const [form, setForm] = useState({ desde: '', hasta: '', motivo: '' })
  const [aviso, setAviso] = useState(null)

  async function agregar(e) {
    e.preventDefault()
    setError(null)
    try {
      const r = await api('/api/padron/dias-no-lectivos', { metodo: 'POST', datos: { ...form, hasta: form.hasta || null } })
      setAviso(r.agregados === 1 ? '1 día agregado' : `${plural(r.agregados, 'día', 'días')} agregados`)
      setForm({ desde: '', hasta: '', motivo: '' })
      cargar()
    } catch (err) { setError(err.message) }
  }

  return (
    <>
      <Encabezado titulo="Días no lectivos" descripcion="Feriados, vacaciones y días sin clase. Las faltas automáticas no se marcan en estos días." />
      {editar && (
        <form className="fila-form" onSubmit={agregar}>
          <label>Desde<input type="date" value={form.desde} onChange={(e) => setForm({ ...form, desde: e.target.value })} required /></label>
          <label>Hasta (opcional)<input type="date" value={form.hasta} onChange={(e) => setForm({ ...form, hasta: e.target.value })} /></label>
          <input placeholder="Motivo" value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} required />
          <button className="boton">Agregar</button>
        </form>
      )}
      {aviso && <p className="tenue">{aviso}</p>}
      <MensajeError texto={error} />
      <Tabla etiqueta="Días no lectivos" cargando={!dias && !error} filas={dias || []}
             vacio={{ icono: CalendarX2, titulo: 'Sin días no lectivos', texto: 'Todos los días de clase del año cuentan para la asistencia.' }}
             columnas={[
               { id: 'fecha', titulo: 'Fecha', nowrap: true, ancho: '220px', celda: (d) => fecha(d.fecha, true) },
               { id: 'motivo', titulo: 'Motivo', celda: (d) => d.motivo },
               editar && { id: 'acciones', acciones: true, celda: (d) => (
                 <MenuAcciones etiqueta={fecha(d.fecha, true)}
                               opciones={[{ texto: 'Quitar', peligro: true, alHacer: () => api(`/api/padron/dias-no-lectivos/${d.id}`, { metodo: 'DELETE' }).then(cargar) }]} />
               ) },
             ].filter(Boolean)} />
    </>
  )
}

// --- Alumnos --------------------------------------------------------------------

const ESTADO_ALUMNO = { activo: ['bien', 'Matriculado'], sin_matricula: ['neutro', 'Sin matrícula'], retirado: ['falta', 'Retirado'] }
const estadoAlumno = (a) => (!a.activo ? 'retirado' : a.seccion ? 'activo' : 'sin_matricula')

function Alumnos({ editar, recojo }) {
  const [secciones] = useCarga('/api/padron/secciones')
  const [params, setParams] = useSearchParams()
  const navegar = useNavigate()
  const filtro = { q: params.get('q') || '', seccion_id: params.get('seccion') || '', estado: params.get('estado') || '' }
  const poner = (k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v); else p.delete(k)
    setParams(p, { replace: true })
  }
  // Desde el buscador del inicio: /panel/padron?alumno=<id> abre su ficha.
  const [abierto, setAbierto] = useState(() => Number(params.get('alumno')) || null)
  const [nuevo, setNuevo] = useState(false)
  const { datos, error, cargando, recargar, paginacion } = usePaginado('/api/padron/alumnos', filtro)

  if (abierto) return <FichaAlumno id={abierto} editar={editar} recojo={recojo} secciones={secciones || []} cerrar={() => { setAbierto(null); recargar() }} />
  if (nuevo) return <FormAlumno secciones={secciones || []} cerrar={(id) => { setNuevo(false); if (id) setAbierto(id); else recargar() }} />

  const filtrado = filtro.q || filtro.seccion_id || filtro.estado
  return (
    <>
      <Encabezado titulo="Alumnos" descripcion="Padrón del año activo: matrícula, documento y apoderados de cada alumno."
                  acciones={editar && (
                    <>
                      <button className="boton secundario" onClick={() => navegar('/panel/padron/importar')}>
                        <FileSpreadsheet size={18} aria-hidden="true" /> Cargar Excel
                      </button>
                      <button className="boton" onClick={() => setNuevo(true)}><UserPlus size={18} aria-hidden="true" /> Nuevo alumno</button>
                    </>
                  )} />
      <Filtros total={datos && plural(datos.total, 'alumno', 'alumnos')}>
        <Buscador valor={filtro.q} cambiar={(v) => poner('q', v)} placeholder="Buscar por nombre o documento" />
        <Selector etiqueta="Sección" valor={filtro.seccion_id} cambiar={(v) => poner('seccion', v)}
                  opciones={[['', 'Todas las secciones'], ...(secciones || []).map((s) => [String(s.id), s.etiqueta])]} />
        <Selector etiqueta="Estado" valor={filtro.estado} cambiar={(v) => poner('estado', v)}
                  opciones={[['', 'Todos los estados'], ['activo', 'Activos'], ['sin_matricula', 'Sin matrícula'], ['retirado', 'Retirados']]} />
      </Filtros>
      <MensajeError texto={error} />
      <Tabla etiqueta="Alumnos" cargando={cargando} filas={datos?.alumnos} alFila={(a) => setAbierto(a.id)}
             vacio={filtrado
               ? { icono: Users, titulo: 'Ningún alumno coincide', texto: 'Prueba con otro nombre, sección o estado.' }
               : { icono: Users, titulo: 'Todavía no hay alumnos', texto: 'Agrégalos uno por uno o cárgalos desde Excel.' }}
             columnas={[
               { id: 'alumno', titulo: 'Alumno', ancho: '34%', celda: (a) => <Persona nombre={`${a.apellidos}, ${a.nombres}`} detalle={`Código ${a.codigo}`} /> },
               { id: 'documento', titulo: 'Documento', nowrap: true, celda: (a) => documento(a.tipo_documento, a.numero_documento) },
               { id: 'seccion', titulo: 'Sección', vacio: (a) => !a.seccion, celda: (a) => a.seccion || <span className="tenue">—</span> },
               { id: 'apoderados', titulo: 'Apoderados', numero: true, alinear: 'derecha', celda: (a) => a.apoderados },
               { id: 'estado', titulo: 'Estado', celda: (a) => {
                 const [tono, texto] = ESTADO_ALUMNO[estadoAlumno(a)]
                 return <Insignia tono={tono}>{texto}</Insignia>
               } },
             ]} />
      {paginacion && paginacion.total > 0 && <Paginacion {...paginacion} />}
    </>
  )
}

function CamposDocumento({ datos, set, tipos = TIPOS_DOC }) {
  return (
    <>
      <select value={datos.tipo_documento} onChange={(e) => set({ ...datos, tipo_documento: e.target.value })}>
        {tipos.map((t) => <option key={t}>{t}</option>)}
      </select>
      <input placeholder="N° documento" value={datos.numero_documento} required
             onChange={(e) => set({ ...datos, numero_documento: e.target.value })} />
      <input placeholder="Apellidos" value={datos.apellidos} required onChange={(e) => set({ ...datos, apellidos: e.target.value })} />
      <input placeholder="Nombres" value={datos.nombres} required onChange={(e) => set({ ...datos, nombres: e.target.value })} />
    </>
  )
}

function FormAlumno({ alumno, secciones, cerrar }) {
  const [datos, setDatos] = useState(alumno ? {
    tipo_documento: alumno.tipo_documento, numero_documento: alumno.numero_documento, nombres: alumno.nombres,
    apellidos: alumno.apellidos, fecha_nacimiento: alumno.fecha_nacimiento || '', seccion_id: alumno.seccion_id || '',
    activo: alumno.activo,
  } : { tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '', fecha_nacimiento: '', seccion_id: '', activo: true })
  const [error, setError] = useState(null)

  async function enviar(e) {
    e.preventDefault()
    const cuerpo = { ...datos, fecha_nacimiento: datos.fecha_nacimiento || null, seccion_id: datos.seccion_id ? Number(datos.seccion_id) : null }
    try {
      const r = alumno
        ? await api(`/api/padron/alumnos/${alumno.id}`, { metodo: 'PUT', datos: cuerpo })
        : await api('/api/padron/alumnos', { metodo: 'POST', datos: cuerpo })
      cerrar(r.id)
    } catch (err) { setError(err.message) }
  }

  return (
    <form className="tarjeta ancho" onSubmit={enviar}>
      <h2>{alumno ? 'Editar alumno' : 'Nuevo alumno'}</h2>
      <div className="fila-form sin-margen"><CamposDocumento datos={datos} set={setDatos} /></div>
      <label>Fecha de nacimiento<input type="date" value={datos.fecha_nacimiento} onChange={(e) => setDatos({ ...datos, fecha_nacimiento: e.target.value })} /></label>
      <label>Sección
        <select value={datos.seccion_id} onChange={(e) => setDatos({ ...datos, seccion_id: e.target.value })}>
          <option value="">Sin matrícula</option>
          {secciones.map((s) => <option key={s.id} value={s.id}>{s.etiqueta}</option>)}
        </select>
      </label>
      {alumno && <label className="check"><input type="checkbox" checked={!datos.activo} onChange={(e) => setDatos({ ...datos, activo: !e.target.checked })} />Retirado</label>}
      <MensajeError texto={error} />
      <div className="acciones">
        <button className="boton">Guardar</button>
        <button type="button" className="enlace" onClick={() => cerrar(alumno?.id)}>Cancelar</button>
      </div>
    </form>
  )
}

function FichaAlumno({ id, editar, recojo, secciones, cerrar }) {
  const [a, setA] = useState(null)
  const [editando, setEditando] = useState(false)
  const [apo, setApo] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => api(`/api/padron/alumnos/${id}`).then(setA).catch((e) => setError(e.message)), [id])
  useEffect(() => { cargar() }, [cargar])

  if (!a) return <MensajeError texto={error} />
  if (editando) return <FormAlumno alumno={a} secciones={secciones} cerrar={() => { setEditando(false); cargar() }} />

  const apoVacio = { tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '', celular: '', correo: '', parentesco: 'Madre', recibe_avisos: true,
    responsable_pago: false }

  async function guardarApo(e) {
    e.preventDefault()
    setError(null)
    try {
      await api(`/api/padron/alumnos/${id}/apoderados`, { metodo: 'POST', datos: { ...apo, celular: apo.celular || null, correo: apo.correo || null } })
      setApo(null)
      cargar()
    } catch (err) { setError(err.message) }
  }

  // Ve la deuda en la app y recibe los avisos de cobro. Marcar a uno desmarca a los demás.
  async function marcarResponsable(p) {
    setError(null)
    try {
      await api(`/api/padron/alumnos/${id}/apoderados`, { metodo: 'POST', datos: {
        tipo_documento: p.tipo_documento, numero_documento: p.numero_documento, nombres: p.nombres,
        apellidos: p.apellidos, celular: p.celular || null, correo: p.correo || null, parentesco: p.parentesco,
        recibe_avisos: p.recibe_avisos, responsable_pago: true } })
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function quitarApo(p) {
    if (!confirm(`¿Quitar a ${p.nombres} ${p.apellidos} como apoderado?`)) return
    await api(`/api/padron/alumnos/${id}/apoderados/${p.id}`, { metodo: 'DELETE' })
    cargar()
  }

  async function nuevoCodigo() {
    if (!confirm('El carnet actual dejará de servir. ¿Generar un código nuevo?')) return
    await api(`/api/padron/alumnos/${id}/nuevo-codigo`, { metodo: 'POST' })
    cargar()
  }

  return (
    <div>
      <button className="enlace" onClick={cerrar}><ArrowLeft size={18} aria-hidden="true" /> Volver a la lista</button>
      <h2>{a.apellidos}, {a.nombres}</h2>
      <p>
        {a.tipo_documento} {a.numero_documento}
        {a.fecha_nacimiento && <> · nació el {fecha(a.fecha_nacimiento)}</>}
        <br />{a.seccion || 'Sin matrícula este año'}{!a.activo && ' · Retirado'}
        <br /><span className="tenue">Código del carnet: <code>{a.codigo}</code></span>
      </p>
      <div className="acciones">
        {editar && <button className="boton" onClick={() => setEditando(true)}>Editar</button>}
        {a.seccion_id && <button className="enlace" onClick={() => descargar(`/api/padron/carnets?alumno_id=${a.id}`, `carnet-${a.numero_documento}.pdf`).catch((e) => setError(e.message))}>Carnet PDF</button>}
        {editar && <button className="enlace" onClick={nuevoCodigo}>Carnet perdido: nuevo código</button>}
      </div>

      <h3>Apoderados</h3>
      {a.apoderados.length === 0 && <p className="tenue">Sin apoderados registrados.</p>}
      <ul className="lista">
        {a.apoderados.map((p) => (
          <li key={p.id}>
            <b>{p.apellidos}, {p.nombres}</b> · {p.parentesco} · {p.tipo_documento} {p.numero_documento}
            {p.celular && <> · {p.celular}</>}
            {p.responsable_pago && <> <Insignia tono="info" titulo="Ve la deuda en la app y recibe los avisos de cobro">Responsable de pago</Insignia></>}
            {editar && !p.responsable_pago && a.apoderados.length > 1 && (
              <button className="enlace" onClick={() => marcarResponsable(p)}>Hacer responsable de pago</button>)}
            {editar && <button className="enlace" onClick={() => quitarApo(p)}>Quitar</button>}
          </li>
        ))}
      </ul>
      {editar && !apo && <button className="boton secundario" onClick={() => setApo(apoVacio)}>Agregar apoderado</button>}
      {apo && (
        <form className="tarjeta ancho" onSubmit={guardarApo}>
          <p className="tenue">Si el apoderado ya existe (por ejemplo, de un hermano), se usa el mismo registro.</p>
          <div className="fila-form sin-margen"><CamposDocumento datos={apo} set={setApo} /></div>
          <div className="fila-form sin-margen">
            <input placeholder="Parentesco" value={apo.parentesco} onChange={(e) => setApo({ ...apo, parentesco: e.target.value })} required />
            <input placeholder="Celular" inputMode="tel" value={apo.celular} onChange={(e) => setApo({ ...apo, celular: e.target.value })} />
            <input placeholder="Correo" type="email" value={apo.correo} onChange={(e) => setApo({ ...apo, correo: e.target.value })} />
          </div>
          <label className="check">
            <input type="checkbox" checked={apo.responsable_pago} onChange={(e) => setApo({ ...apo, responsable_pago: e.target.checked })} />
            Responsable de pago (ve la deuda y recibe los avisos de cobro)
          </label>
          <div className="acciones">
            <button className="boton">Guardar</button>
            <button type="button" className="enlace" onClick={() => setApo(null)}>Cancelar</button>
          </div>
        </form>
      )}
      <MensajeError texto={error} />
      {recojo?.ver && <RecojoAlumno alumnoId={a.id} editar={recojo.editar} />}
    </div>
  )
}

// --- Importar Excel ---------------------------------------------------------------

const NOMBRES_RESUMEN = {
  alumnos_nuevos: 'Alumnos nuevos', alumnos_actualizados: 'Alumnos con datos cambiados',
  matriculas_nuevas: 'Matrículas nuevas', cambios_seccion: 'Cambios de sección',
  apoderados_nuevos: 'Apoderados nuevos', apoderados_actualizados: 'Apoderados con datos cambiados',
  vinculos_nuevos: 'Vínculos alumno–apoderado nuevos', personal_nuevo: 'Personal nuevo',
  personal_actualizado: 'Personal con datos cambiados',
}

function Importar() {
  const [archivo, setArchivo] = useState(null)
  const [campo, setCampo] = useState(0)  // cambia la key del input para vaciarlo
  const [informe, setInforme] = useState(null)
  const [hecho, setHecho] = useState(null)
  const [error, setError] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  async function enviar(paso) {
    setError(null)
    setOcupado(true)
    try {
      const r = await api(`/api/padron/importacion/${paso}`, { metodo: 'POST', archivo })
      if (paso === 'confirmar') {
        setHecho(r)
        setInforme(null)
        setArchivo(null)
        setCampo((n) => n + 1)
        if (r.cartas_pdf) descargarCartas(r.cartas_pdf)
      } else {
        setInforme(r)
      }
    } catch (err) { setError(err.message) } finally { setOcupado(false) }
  }

  function descargarCartas(b64) {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    guardarArchivo(new Blob([bytes], { type: 'application/pdf' }), 'accesos-personal.pdf')
  }

  return (
    <>
      <Encabezado titulo="Carga masiva desde Excel" descripcion="Alumnos con sus apoderados y personal, en un solo archivo." />
      <ol className="pasos">
        <li>Descarga la plantilla. Trae las hojas Alumnos y Personal, y como referencia las secciones y roles que ya existen.
          <br /><button className="enlace" onClick={() => descargar('/api/padron/importacion/plantilla', 'plantilla-padron.xlsx').catch((e) => setError(e.message))}>Descargar plantilla</button>
        </li>
        <li>Llénala y súbela. Primero verás una vista previa con los errores; no se guarda nada hasta confirmar.</li>
      </ol>
      <div className="fila-form">
        <input key={campo} type="file" accept=".xlsx" onChange={(e) => { setArchivo(e.target.files[0] || null); setInforme(null); setHecho(null) }} />
        <button className="boton" disabled={!archivo || ocupado} onClick={() => enviar('vista-previa')}>Revisar</button>
      </div>
      <MensajeError texto={error} />

      {informe && (
        <div className="tarjeta ancho">
          <h3>Vista previa · año {informe.anio}</h3>
          <Resumen resumen={informe.resumen} />
          {informe.total_errores > 0 ? (
            <>
              <p className="error">{informe.total_errores === 1 ? 'Hay 1 error' : `Hay ${plural(informe.total_errores, 'error', 'errores')}`}. Corrígelos en el Excel y vuelve a subirlo.</p>
              <Tabla etiqueta="Errores del Excel" filas={informe.errores.map((e, i) => ({ ...e, id: i }))}
                     columnas={[
                       { id: 'problema', titulo: 'Problema', claseCelda: () => 'error-celda', celda: (e) => e.mensaje },
                       { id: 'hoja', titulo: 'Hoja', celda: (e) => e.hoja },
                       { id: 'fila', titulo: 'Fila', numero: true, alinear: 'derecha', vacio: (e) => e.fila == null, celda: (e) => e.fila ?? '—' },
                       { id: 'columna', titulo: 'Columna', vacio: (e) => !e.columna, celda: (e) => e.columna || <span className="tenue">—</span> },
                       { id: 'estado', titulo: 'Estado', celda: () => <Insignia tono="falta">Error</Insignia> },
                     ]} />
              {informe.total_errores > informe.errores.length && <p className="tenue">Se muestran los primeros {informe.errores.length}.</p>}
            </>
          ) : (
            <div className="acciones">
              <button className="boton" disabled={ocupado} onClick={() => enviar('confirmar')}>Confirmar y guardar</button>
              <span className="tenue">Sin errores.</span>
            </div>
          )}
        </div>
      )}

      {hecho && (
        <div className="aviso">
          <b>Padrón guardado.</b>
          <Resumen resumen={hecho.resumen} />
          {hecho.cartas_pdf && (
            <p>Se descargó <b>accesos-personal.pdf</b> con el usuario y la clave temporal {hecho.personal_nuevo === 1 ? 'de la persona nueva' : `de las ${plural(hecho.personal_nuevo, 'persona', 'personas')} nuevas`}.
              Es la única copia: imprímelo y entrégalo en mano.{' '}
              <button className="enlace" onClick={() => descargarCartas(hecho.cartas_pdf)}>Descargar otra vez</button></p>
          )}
        </div>
      )}
    </>
  )
}

function Resumen({ resumen }) {
  const filas = Object.entries(resumen).filter(([, n]) => n > 0)
  if (filas.length === 0) return <p className="tenue">No hay cambios.</p>
  return <ul className="lista">{filas.map(([k, n]) => <li key={k}>{NOMBRES_RESUMEN[k] || k}: <b>{n}</b></li>)}</ul>
}

function fecha(iso, conDia = false) {
  const [a, m, d] = iso.split('-').map(Number)
  const f = new Date(a, m - 1, d)
  return f.toLocaleDateString('es-PE', conDia ? { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' } : undefined)
}
