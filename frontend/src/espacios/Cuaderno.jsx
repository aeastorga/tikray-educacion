import { ArrowLeft, MessageCircle, Paperclip } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, descargar } from '../api.js'
import './cuaderno.css'

export const TIPOS = {
  comunicado: 'Comunicado', incidencia: 'Incidencia', citacion: 'Citación',
  justificacion: 'Justificación', permiso_salida: 'Permiso de salida',
}
const ESTADOS = { pendiente: 'Por aprobar', aprobada: 'Aprobada', rechazada: 'Rechazada', anulada: 'Anulada' }
const ALCANCES = { colegio: 'Todo el colegio', nivel: 'Un nivel', grado: 'Un grado', seccion: 'Una sección', alumno: 'Un alumno' }
// Lo que firma el padre según el tipo.
export const FIRMA = { comunicado: 'Firmó', incidencia: 'Enterado', citacion: 'Confirmó' }

export function fechaHora(iso) {
  return iso ? new Date(iso).toLocaleString('es-PE', { timeZone: 'America/Lima', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit' }).replace(/\s/g, '\u00A0') : ''  // una sola línea en las tablas
}

export function fechaCorta(iso) {
  return iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('es-PE', { day: 'numeric', month: 'short' }) : ''
}

// Lo propio de cada tipo, en una línea: fecha de la citación, días justificados, hora de salida.
export function Detalles({ e }) {
  const partes = []
  if (e.cita_en) partes.push(`Cita: ${fechaHora(e.cita_en)}${e.lugar ? ` · ${e.lugar}` : ''}`)
  if (e.tipo === 'justificacion') partes.push(e.hasta && e.hasta !== e.desde ? `Del ${fechaCorta(e.desde)} al ${fechaCorta(e.hasta)}` : `Día ${fechaCorta(e.desde)}`)
  if (e.tipo === 'permiso_salida') partes.push(`Sale el ${fechaCorta(e.desde)} a las ${e.hora_salida} · Recoge: ${e.recoge}`)
  if (e.estado === 'anulada') partes.push(`Anulada: ${e.motivo_anulacion}`)
  else if (e.estado) partes.push(ESTADOS[e.estado] + (e.nota_resolucion ? `: ${e.nota_resolucion}` : ''))
  return partes.length ? <p className="cuaderno-detalles">{partes.join(' · ')}</p> : null
}

export default function Cuaderno({ editar, docentes }) {
  return (
    <section>
      <nav className="subpestanas">
        <NavLink to="/panel/cuaderno" end>Bandeja</NavLink>
        {editar && <NavLink to="/panel/cuaderno/escribir">Escribir</NavLink>}
        {docentes && <NavLink to="/panel/cuaderno/docentes">Docentes por sección</NavLink>}
      </nav>
      <Routes>
        <Route index element={<Bandeja />} />
        {editar && <Route path="escribir" element={<Escribir />} />}
        {docentes && <Route path="docentes" element={<Docentes />} />}
        <Route path=":id" element={<Detalle editar={editar} />} />
      </Routes>
    </section>
  )
}

// --- Bandeja ---------------------------------------------------------------------------

function Bandeja() {
  const navegar = useNavigate()
  const [filtro, setFiltro] = useState({ tipo: '', pendientes: false })
  const [lista, setLista] = useState(null)
  const [hayMas, setHayMas] = useState(false)
  const [error, setError] = useState(null)

  const consulta = useCallback((antes) => {
    const p = new URLSearchParams()
    if (filtro.tipo) p.set('tipo', filtro.tipo)
    if (filtro.pendientes) p.set('pendientes', 'true')
    if (antes) p.set('antes_de', antes)
    return api(`/api/cuaderno/entradas?${p}`)
  }, [filtro])

  useEffect(() => {
    setError(null)
    consulta().then((l) => { setLista(l); setHayMas(l.length === 50) }).catch((e) => setError(e.message))
  }, [consulta])

  async function mas() {
    const l = await consulta(lista[lista.length - 1].id)
    setLista([...lista, ...l])
    setHayMas(l.length === 50)
  }

  return (
    <>
      <div className="fila-form sin-margen">
        <select value={filtro.tipo} onChange={(e) => setFiltro({ ...filtro, tipo: e.target.value })} aria-label="Tipo">
          <option value="">Todo</option>
          {Object.entries(TIPOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="check">
          <input type="checkbox" checked={filtro.pendientes}
                 onChange={(e) => setFiltro({ ...filtro, pendientes: e.target.checked })} />
          Solo lo que espera al colegio
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      {lista && lista.length === 0 && <p className="tenue">No hay nada aquí todavía.</p>}
      {lista && lista.length > 0 && (
        <table>
          <thead><tr><th>Fecha</th><th>Tipo</th><th>Asunto</th><th>Para</th><th>Familias</th></tr></thead>
          <tbody>
            {lista.map((e) => (
              <tr key={e.id} className="clic" onClick={() => navegar(`/panel/cuaderno/${e.id}`)}>
                <td className="tenue fecha">{fechaHora(e.creado_en)}</td>
                <td>
                  <span className={`tipo-cuaderno ${e.tipo}`}>{TIPOS[e.tipo]}</span>
                  {e.estado && <span className={`estado-cuaderno ${e.estado}`}>{ESTADOS[e.estado]}</span>}
                </td>
                <td>
                  {e.espera_al_colegio && <span className="punto" title="Espera respuesta del colegio" />}
                  {e.titulo}
                  {e.adjuntos > 0 && <span className="tenue icono-texto"> · <Paperclip size={14} aria-label="adjuntos" /> {e.adjuntos}</span>}
                  {e.respuestas > 0 && <span className="tenue icono-texto"> · <MessageCircle size={14} aria-label="respuestas" /> {e.respuestas}</span>}
                  {e.de_familia && <span className="tenue"> · enviado por la familia</span>}
                </td>
                <td>{e.destino}</td>
                <td className="tenue">
                  {e.pide_firma ? `${e.firmados}/${e.apoderados} ${FIRMA[e.tipo].toLowerCase()}` : `${e.vistos}/${e.apoderados} vieron`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {hayMas && <button className="enlace" onClick={mas}>Ver más</button>}
    </>
  )
}

// --- Detalle -----------------------------------------------------------------------------

function Detalle({ editar }) {
  const { id } = useParams()
  const navegar = useNavigate()
  const [e, setE] = useState(null)
  const [error, setError] = useState(null)
  const [respuesta, setRespuesta] = useState('')
  const [soloPendientes, setSoloPendientes] = useState(false)
  const [nota, setNota] = useState('')

  const cargar = useCallback(() => api(`/api/cuaderno/entradas/${id}`).then(setE).catch((err) => setError(err.message)), [id])
  useEffect(() => { cargar() }, [cargar])

  async function responder(ev) {
    ev.preventDefault()
    setError(null)
    try {
      await api(`/api/cuaderno/entradas/${id}/respuestas`, { metodo: 'POST', datos: { cuerpo: respuesta } })
      setRespuesta('')
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function anular() {
    const motivo = prompt(e.tipo === 'justificacion'
      ? 'Motivo de la anulación (las faltas que justificaba vuelven a ser faltas):' : 'Motivo de la anulación:')
    if (!motivo?.trim()) return
    setError(null)
    try { await api(`/api/cuaderno/entradas/${id}/anular`, { metodo: 'POST', datos: { motivo } }); cargar() }
    catch (err) { setError(err.message) }
  }

  async function resolver(estado) {
    setError(null)
    try {
      await api(`/api/cuaderno/entradas/${id}/resolver`, { metodo: 'POST', datos: { estado, nota: nota || null } })
      cargar()
    } catch (err) { setError(err.message) }
  }

  if (error && !e) return <p className="error">{error}</p>
  if (!e) return <p className="tenue">Cargando…</p>
  const lectores = soloPendientes ? e.lectores.filter((l) => (e.pide_firma ? !l.firmado_en : !l.visto_en)) : e.lectores
  const familias = new Set(e.lectores.map((l) => l.apoderado))
  const firmaron = new Set(e.lectores.filter((l) => l.firmado_en).map((l) => l.apoderado))
  const vieron = new Set(e.lectores.filter((l) => l.visto_en).map((l) => l.apoderado))

  return (
    <article className="cuaderno-detalle">
      <button className="enlace" onClick={() => navegar('/panel/cuaderno')}><ArrowLeft size={18} aria-hidden="true" /> Bandeja</button>
      <p className="tenue">
        <span className={`tipo-cuaderno ${e.tipo}`}>{TIPOS[e.tipo]}</span> {e.destino} · {fechaHora(e.creado_en)}
        {e.autor && ` · ${e.de_familia ? 'Enviado por' : 'Escrito por'} ${e.autor}`}
      </p>
      <h2>{e.titulo}</h2>
      <Detalles e={e} />
      {e.cuerpo && <p className="cuaderno-cuerpo">{e.cuerpo}</p>}
      <Adjuntos lista={e.adjuntos} ruta="/api/cuaderno/adjuntos" />

      {editar && e.estado === 'pendiente' && (
        <div className="aviso">
          <p className="sin-margen"><b>{e.tipo === 'justificacion' ? '¿Se acepta esta justificación?' : '¿Se autoriza esta salida?'}</b></p>
          <div className="fila-form">
            <input placeholder="Nota para la familia (opcional)" value={nota} maxLength={300} onChange={(ev) => setNota(ev.target.value)} />
            <button className="boton" onClick={() => resolver('aprobada')}>Aprobar</button>
            <button className="boton secundario" onClick={() => resolver('rechazada')}>Rechazar</button>
          </div>
        </div>
      )}

      {editar && e.estado === 'aprobada' && (
        <p><button className="enlace" onClick={anular}>Anular {e.tipo === 'justificacion' ? 'la justificación' : 'el permiso'}</button></p>
      )}

      <h3>Hilo</h3>
      {e.mensajes.length === 0 && <p className="tenue">Sin respuestas.</p>}
      <ul className="hilo">
        {e.mensajes.map((m) => (
          <li key={m.id} className={m.de_familia ? 'de-familia' : 'del-colegio'}>
            <span className="tenue pequeno">{m.autor} · {fechaHora(m.creado_en)}</span>
            <p>{m.cuerpo}</p>
          </li>
        ))}
      </ul>
      {editar && (
        <form className="fila-form" onSubmit={responder}>
          <textarea value={respuesta} required maxLength={4000} rows={2} placeholder="Responder a la familia"
                    onChange={(ev) => setRespuesta(ev.target.value)} />
          <button className="boton">Responder</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}

      <h3>
        Familias: {e.pide_firma ? `${firmaron.size} de ${familias.size} ${FIRMA[e.tipo].toLowerCase()}` : `${vieron.size} de ${familias.size} lo vieron`}
      </h3>
      <label className="check">
        <input type="checkbox" checked={soloPendientes} onChange={(ev) => setSoloPendientes(ev.target.checked)} />
        Solo quienes aún no {e.pide_firma ? 'firman' : 'lo ven'}
      </label>
      <table>
        <thead><tr><th>Alumno</th><th>Apoderado</th><th>Vio</th>{e.pide_firma && <th>{FIRMA[e.tipo]}</th>}</tr></thead>
        <tbody>
          {lectores.map((l) => (
            <tr key={`${l.alumno}-${l.apoderado}`}>
              <td>{l.alumno}</td>
              <td>{l.apoderado}{l.parentesco && <span className="tenue"> ({l.parentesco})</span>}
                {!l.con_app && <span className="tenue"> · sin la app</span>}</td>
              <td>{l.visto_en ? fechaHora(l.visto_en) : <span className="tenue">No</span>}</td>
              {e.pide_firma && <td>{l.firmado_en ? fechaHora(l.firmado_en) : <span className="falta-firma">No</span>}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  )
}

export function Adjuntos({ lista, ruta }) {
  const [error, setError] = useState(null)
  if (!lista?.length) return null
  async function bajar(a) {
    setError(null)
    try { await descargar(`${ruta}/${a.id}`, a.nombre) } catch (err) { setError(err.message) }
  }
  return (
    <div className="adjuntos">
      {lista.map((a) => (
        <button key={a.id} className="chip" onClick={() => bajar(a)}><Paperclip size={14} aria-hidden="true" /> {a.nombre} <span className="tenue">({tamano(a.tamano)})</span></button>
      ))}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function tamano(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// --- Escribir -------------------------------------------------------------------------------

const VACIO = {
  tipo: 'comunicado', alcance: 'colegio', nivel_id: '', grado_id: '', seccion_id: '', alumno: null, titulo: '',
  cuerpo: '', pide_firma: true, cita_en: '', lugar: '', desde: '', hasta: '', hora_salida: '', recoge: '',
}

function Escribir() {
  const navegar = useNavigate()
  const [op, setOp] = useState(null)
  const [f, setF] = useState(VACIO)
  const [archivos, setArchivos] = useState([])
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    api('/api/cuaderno/opciones').then((o) => {
      setOp(o)
      if (!o.todo_el_colegio) setF((x) => ({ ...x, alcance: 'seccion' }))
    }).catch((e) => setError(e.message))
  }, [])

  const cambiar = (campo) => (ev) => setF({ ...f, [campo]: ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value })
  const alcance = f.tipo === 'comunicado' ? f.alcance : 'alumno'

  async function enviar(ev) {
    ev.preventDefault()
    setError(null)
    if (alcance === 'alumno' && !f.alumno) { setError('Elige al alumno'); return }
    const n = (v) => (v ? Number(v) : null)
    const datos = {
      tipo: f.tipo, alcance, titulo: f.titulo, cuerpo: f.cuerpo, pide_firma: f.pide_firma,
      nivel_id: alcance === 'nivel' ? n(f.nivel_id) : null, grado_id: alcance === 'grado' ? n(f.grado_id) : null,
      seccion_id: alcance === 'seccion' ? n(f.seccion_id) : null, alumno_id: alcance === 'alumno' ? f.alumno.id : null,
      cita_en: f.tipo === 'citacion' ? f.cita_en : null, lugar: f.tipo === 'citacion' ? f.lugar || null : null,
      desde: ['justificacion', 'permiso_salida'].includes(f.tipo) ? f.desde : null,
      hasta: f.tipo === 'justificacion' ? f.hasta || null : null,
      hora_salida: f.tipo === 'permiso_salida' ? f.hora_salida : null,
      recoge: f.tipo === 'permiso_salida' ? f.recoge : null,
    }
    const formulario = new FormData()
    formulario.append('datos', JSON.stringify(datos))
    for (const a of archivos) formulario.append('archivos', a)
    setEnviando(true)
    try {
      const r = await api('/api/cuaderno/entradas', { metodo: 'POST', formulario })
      navegar(`/panel/cuaderno/${r.id}`)
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  if (!op) return error ? <p className="error">{error}</p> : <p className="tenue">Cargando…</p>
  if (!op.todo_el_colegio && op.secciones.length === 0) {
    return <p className="tenue">Aún no tienes secciones a tu cargo. Pide a la dirección que te asigne en “Docentes por sección”.</p>
  }

  return (
    <form className="tarjeta ancho" onSubmit={enviar}>
      <label>Tipo
        <select value={f.tipo} onChange={cambiar('tipo')}>
          {Object.entries(TIPOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      {f.tipo === 'comunicado' && (
        <label>Para
          <select value={f.alcance} onChange={cambiar('alcance')}>
            {Object.entries(ALCANCES).filter(([k]) => op.todo_el_colegio || ['seccion', 'alumno'].includes(k))
              .map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      )}
      {alcance === 'nivel' && <Opcion valor={f.nivel_id} onChange={cambiar('nivel_id')} lista={op.niveles} nombre="Nivel" />}
      {alcance === 'grado' && <Opcion valor={f.grado_id} onChange={cambiar('grado_id')} lista={op.grados} nombre="Grado" />}
      {alcance === 'seccion' && <Opcion valor={f.seccion_id} onChange={cambiar('seccion_id')} lista={op.secciones} nombre="Sección" />}
      {alcance === 'alumno' && <ElegirAlumno valor={f.alumno} onChange={(a) => setF({ ...f, alumno: a })} secciones={op.secciones} />}

      <label>{f.tipo === 'justificacion' ? 'Motivo' : 'Asunto'}
        <input value={f.titulo} onChange={cambiar('titulo')} required maxLength={200} />
      </label>
      <label>Detalle
        <textarea value={f.cuerpo} onChange={cambiar('cuerpo')} rows={5} maxLength={10000} />
      </label>

      {f.tipo === 'comunicado' && (
        <label className="check">
          <input type="checkbox" checked={f.pide_firma} onChange={cambiar('pide_firma')} />
          Pedir firma de lectura a cada apoderado
        </label>
      )}
      {f.tipo === 'citacion' && (
        <div className="fila-form sin-margen">
          <label>Fecha y hora<input type="datetime-local" value={f.cita_en} onChange={cambiar('cita_en')} required /></label>
          <label>Lugar<input value={f.lugar} onChange={cambiar('lugar')} maxLength={120} placeholder="Dirección, aula…" /></label>
        </div>
      )}
      {f.tipo === 'justificacion' && (
        <div className="fila-form sin-margen">
          <label>Desde<input type="date" value={f.desde} onChange={cambiar('desde')} required /></label>
          <label>Hasta<input type="date" value={f.hasta} onChange={cambiar('hasta')} min={f.desde} /></label>
        </div>
      )}
      {f.tipo === 'permiso_salida' && (
        <div className="fila-form sin-margen">
          <label>Día<input type="date" value={f.desde} onChange={cambiar('desde')} required /></label>
          <label>Hora<input type="time" value={f.hora_salida} onChange={cambiar('hora_salida')} required /></label>
          <label>Lo recoge<input value={f.recoge} onChange={cambiar('recoge')} required maxLength={120} /></label>
        </div>
      )}

      <label>Adjuntos (PDF, imágenes, Word o Excel; hasta 5 de 10 MB)
        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.docx,.xlsx"
               onChange={(ev) => setArchivos([...ev.target.files].slice(0, 5))} />
      </label>
      {error && <p className="error">{error}</p>}
      <p className="tenue pequeno">
        {['justificacion', 'permiso_salida'].includes(f.tipo) ? 'Lo que registra el colegio queda aprobado. ' : ''}
        Las familias con la app reciben un aviso en el celular.
      </p>
      <button className="boton" disabled={enviando}>{enviando ? 'Enviando…' : 'Enviar'}</button>
    </form>
  )
}

function Opcion({ valor, onChange, lista, nombre }) {
  return (
    <label>{nombre}
      <select value={valor} onChange={onChange} required>
        <option value="">Elige…</option>
        {lista.map((x) => <option key={x.id} value={x.id}>{x.nombre}{x.nivel ? ` · ${x.nivel}` : ''}</option>)}
      </select>
    </label>
  )
}

function ElegirAlumno({ valor, onChange, secciones }) {
  const [q, setQ] = useState('')
  const [seccion, setSeccion] = useState('')
  const [lista, setLista] = useState([])

  useEffect(() => {
    if (q.trim().length < 2 && !seccion) { setLista([]); return }
    const p = new URLSearchParams({ q: q.trim() })
    if (seccion) p.set('seccion_id', seccion)
    const t = setTimeout(() => api(`/api/cuaderno/alumnos?${p}`).then(setLista).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q, seccion])

  if (valor) {
    return (
      <p>Alumno: <b>{valor.nombre}</b> <span className="tenue">{valor.seccion}</span>{' '}
        <button type="button" className="enlace" onClick={() => onChange(null)}>Cambiar</button></p>
    )
  }
  return (
    <div className="elegir-alumno">
      <div className="fila-form sin-margen">
        <input placeholder="Buscar alumno por nombre o DNI" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={seccion} onChange={(e) => setSeccion(e.target.value)} aria-label="Sección">
          <option value="">Todas las secciones</option>
          {secciones.map((s) => <option key={s.id} value={s.id}>{s.nombre} · {s.nivel}</option>)}
        </select>
      </div>
      <ul className="lista-elegir">
        {lista.map((a) => (
          <li key={a.id}><button type="button" className="enlace" onClick={() => onChange(a)}>{a.nombre}</button>
            <span className="tenue"> {a.seccion}</span></li>
        ))}
      </ul>
    </div>
  )
}

// --- Docentes por sección -------------------------------------------------------------------

function Docentes() {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => api('/api/cuaderno/docentes').then(setDatos).catch((e) => setError(e.message)), [])
  useEffect(() => { cargar() }, [cargar])

  async function guardar(seccion, ids) {
    setError(null)
    try {
      await api(`/api/cuaderno/secciones/${seccion.id}/docentes`, { metodo: 'PUT', datos: { usuario_ids: ids } })
      cargar()
    } catch (e) { setError(e.message) }
  }

  if (!datos) return error ? <p className="error">{error}</p> : <p className="tenue">Cargando…</p>
  const nombres = Object.fromEntries(datos.personal.map((p) => [p.id, p.nombre]))
  return (
    <>
      <p className="tenue">
        Quien tenga un rol con “Solo ve las secciones a su cargo” (en Roles) solo verá y escribirá en el cuaderno de estas secciones.
      </p>
      {error && <p className="error">{error}</p>}
      {datos.secciones.length === 0 && <p className="tenue">No hay secciones en el año activo.</p>}
      <table>
        <thead><tr><th>Sección</th><th>A cargo</th></tr></thead>
        <tbody>
          {datos.secciones.map((s) => (
            <tr key={s.id}>
              <td>{s.nombre}</td>
              <td>
                {s.docentes.map((d) => (
                  <span key={d} className="chip">{nombres[d] || d}
                    <button className="enlace" aria-label="Quitar" onClick={() => guardar(s, s.docentes.filter((x) => x !== d))}>×</button>
                  </span>
                ))}
                <select value="" aria-label="Agregar" onChange={(e) => e.target.value && guardar(s, [...s.docentes, Number(e.target.value)])}>
                  <option value="">+ Agregar…</option>
                  {datos.personal.filter((p) => !s.docentes.includes(p.id)).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
