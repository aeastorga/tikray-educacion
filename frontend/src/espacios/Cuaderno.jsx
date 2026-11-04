import {
  ArrowLeft, Award, CalendarClock, DoorOpen, FileCheck, Inbox, Megaphone, TriangleAlert, Users,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, descargar } from '../api.js'
import {
  Buscador, Encabezado, fechaHora as fechaHoraTabla, Filtros, Insignia, Paginacion, plural, Selector, Tabla, usePaginado,
} from './comun/index.js'
import './cuaderno.css'

export const TIPOS = {
  comunicado: 'Comunicado', incidencia: 'Incidencia', citacion: 'Citación',
  justificacion: 'Justificación', permiso_salida: 'Permiso de salida',
}
const ESTADOS = { pendiente: 'Por aprobar', aprobada: 'Aprobada', rechazada: 'Rechazada', anulada: 'Anulada' }
const TONO_ESTADO = { pendiente: 'tarde', aprobada: 'bien', rechazada: 'falta', anulada: 'neutro' }
const ICONO_TIPO = {
  comunicado: Megaphone, incidencia: TriangleAlert, citacion: CalendarClock, justificacion: FileCheck, permiso_salida: DoorOpen,
}

// Tipo como insignia con su ícono; una incidencia de mérito lleva la medalla.
export function TipoEntrada({ e }) {
  const merito = e.categoria?.tipo === 'merito'
  const tono = merito ? 'bien' : e.tipo === 'incidencia' ? 'tarde' : e.tipo === 'comunicado' || e.tipo === 'citacion' ? 'info' : 'neutro'
  return <Insignia tono={tono} icono={merito ? Award : ICONO_TIPO[e.tipo]}>{TIPOS[e.tipo]}</Insignia>
}

// A quién va: el nombre arriba; la sección del alumno debajo, en tenue y sin partirse.
function Destino({ e }) {
  return <>{e.destino}{e.destino_seccion && <span className="destino-seccion">{e.destino_seccion}</span>}</>
}

function EstadoEntrada({ e }) {
  if (programadoPendiente(e)) return <Insignia tono="info" titulo={`Sale el ${fechaHora(e.programado_para)}`}>Programado</Insignia>
  if (e.estado) return <Insignia tono={TONO_ESTADO[e.estado]}>{ESTADOS[e.estado]}</Insignia>
  if (e.espera_al_colegio) return <Insignia tono="tarde">Por responder</Insignia>
  return <Insignia tono="bien">Enviado</Insignia>
}
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

// Perú no cambia de hora: un datetime-local se lee siempre como hora de Lima.
const conZonaLima = (local) => `${local.length === 16 ? `${local}:00` : local}-05:00`
export const programadoPendiente = (e) => e.programado_para && new Date(e.programado_para) > new Date()

export function Categoria({ c }) {
  return c ? <span className={`categoria-cuaderno ${c.tipo}`}>{c.tipo === 'merito' ? '★ ' : ''}{c.nombre}</span> : null
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
  const [params, setParams] = useSearchParams()
  const filtro = { tipo: params.get('tipo') || '', pendientes: params.get('pendientes') === '1' }
  const poner = (k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v === true ? '1' : v); else p.delete(k)
    setParams(p, { replace: true })
  }
  const { datos, error, cargando, paginacion } = usePaginado('/api/cuaderno/entradas', filtro, { demora: 0 })

  const columnas = [
    { id: 'fecha', titulo: 'Fecha', nowrap: true, ancho: '150px',
      celda: (e) => <span className="tenue">{fechaHoraTabla(programadoPendiente(e) ? e.programado_para : e.creado_en)}</span> },
    { id: 'tipo', titulo: 'Tipo', nowrap: true, celda: (e) => <TipoEntrada e={e} /> },
    { id: 'asunto', titulo: 'Asunto', ancho: '28%', celda: (e) => {
      const extra = [
        e.adjuntos > 0 && plural(e.adjuntos, 'adjunto', 'adjuntos'),
        e.respuestas > 0 && plural(e.respuestas, 'respuesta', 'respuestas'),
        e.categoria && e.categoria.nombre,
        e.de_familia && 'enviado por la familia',
      ].filter(Boolean)
      return (
        <>
          <span className="asunto-entrada">
            {e.espera_al_colegio && <span className="punto-espera" title="Espera al colegio" />}
            <b>{e.titulo}</b>
          </span>
          {extra.length > 0 && <span className="segunda-linea">{extra.join(' · ')}</span>}
        </>
      )
    } },
    { id: 'para', titulo: 'Para', ancho: '22%', celda: (e) => <Destino e={e} /> },
    { id: 'familias', titulo: 'Familias', ocultarEnCelular: true, vacio: (e) => !e.apoderados, celda: (e) => {
      const hechos = e.pide_firma ? e.firmados : e.vistos
      const verbo = e.pide_firma ? FIRMA[e.tipo].toLowerCase() : 'vieron'
      if (!e.apoderados) return <span className="tenue">—</span>
      return (
        <span className="progreso" title={`${hechos} de ${plural(e.apoderados, 'familia', 'familias')}`}>
          <span className="progreso-barra"><i style={{ width: `${Math.round((100 * hechos) / e.apoderados)}%` }} /></span>
          <span>{hechos.toLocaleString('es-PE')}/{e.apoderados.toLocaleString('es-PE')} {verbo}</span>
        </span>
      )
    } },
    { id: 'estado', titulo: 'Estado', nowrap: true, celda: (e) => <EstadoEntrada e={e} /> },
  ]

  return (
    <>
      <Encabezado titulo="Bandeja" descripcion="Comunicados, incidencias, citaciones, justificaciones y permisos de salida." />
      <Filtros total={datos && plural(datos.total, 'entrada', 'entradas')}>
        <Selector etiqueta="Tipo" valor={filtro.tipo} cambiar={(v) => poner('tipo', v)}
                  opciones={[['', 'Todos los tipos'], ...Object.entries(TIPOS)]} />
        <label className="check">
          <input type="checkbox" checked={filtro.pendientes} onChange={(e) => poner('pendientes', e.target.checked)} />
          Solo lo que espera al colegio
        </label>
      </Filtros>
      {error && <p className="error">{error}</p>}
      <Tabla etiqueta="Bandeja del cuaderno" cargando={cargando} filas={datos?.entradas} columnas={columnas}
             alFila={(e) => navegar(`/panel/cuaderno/${e.id}`)}
             claseFila={(e) => (e.espera_al_colegio ? 'destacada' : '')}
             vacio={filtro.tipo || filtro.pendientes
               ? { icono: Inbox, titulo: 'Nada pendiente aquí', texto: 'No hay entradas con estos filtros.' }
               : { icono: Inbox, titulo: 'El cuaderno está vacío', texto: 'Lo que escriban el colegio y las familias aparecerá aquí.' }} />
      {paginacion && paginacion.total > 0 && <Paginacion {...paginacion} />}
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

  async function cancelar() {
    if (!window.confirm('¿Cancelar este comunicado? No saldrá y se borra.')) return
    setError(null)
    try { await api(`/api/cuaderno/entradas/${id}/cancelar`, { metodo: 'POST' }); navegar('/panel/cuaderno') }
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

  return (
    <article className="cuaderno-detalle">
      <button className="enlace" onClick={() => navegar('/panel/cuaderno')}><ArrowLeft size={18} aria-hidden="true" /> Bandeja</button>
      <p className="tenue">
        <TipoEntrada e={e} /> {e.destino}{e.destino_seccion && <> <span className="nowrap">({e.destino_seccion})</span></>} · {fechaHora(e.creado_en)}
        {e.autor && ` · ${e.de_familia ? 'Enviado por' : 'Escrito por'} ${e.autor}`}
        {' '}<Categoria c={e.categoria} />
      </p>
      <h2>{e.titulo}</h2>
      {programadoPendiente(e) && (
        <div className="aviso aviso-programado">
          <p className="sin-margen"><b>Programado para el {fechaHora(e.programado_para)}</b> Hasta entonces las familias
            no lo ven ni reciben el aviso.</p>
          {editar && <button className="boton secundario" onClick={cancelar}>Cancelar envío</button>}
        </div>
      )}
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

      <Lectores e={e} />
    </article>
  )
}

// Familias de una entrada (en la demo, 904): por páginas y con buscador.
function Lectores({ e }) {
  const [q, setQ] = useState('')
  const [pendientes, setPendientes] = useState(false)
  const { datos, error, cargando, paginacion } = usePaginado(`/api/cuaderno/entradas/${e.id}/lectores`, { q, pendientes })
  const f = e.familias
  const firma = FIRMA[e.tipo]
  const vacio = q || pendientes
    ? { icono: Users, titulo: pendientes && !q ? (e.pide_firma ? 'Todas firmaron' : 'Todas lo vieron') : 'Nadie coincide',
        texto: pendientes && !q ? null : 'Prueba con otro nombre.' }
    : { icono: Users, titulo: 'Sin familias', texto: 'Esta entrada no llegó a ningún apoderado.' }
  return (
    <section className="lectores">
      <Encabezado nivel={3} titulo="Familias"
                  descripcion={e.pide_firma
                    ? `${f.firmaron.toLocaleString('es-PE')} de ${plural(f.total, 'familia', 'familias')} ${firma.toLowerCase()} · ${f.vieron.toLocaleString('es-PE')} lo vieron`
                    : `${f.vieron.toLocaleString('es-PE')} de ${plural(f.total, 'familia', 'familias')} lo vieron`} />
      <Filtros total={datos && plural(datos.total, 'fila', 'filas')}>
        <Buscador valor={q} cambiar={setQ} placeholder="Buscar alumno o apoderado" />
        <label className="check">
          <input type="checkbox" checked={pendientes} onChange={(ev) => setPendientes(ev.target.checked)} />
          Solo quienes aún no {e.pide_firma ? 'firman' : 'lo ven'}
        </label>
      </Filtros>
      {error && <p className="error">{error}</p>}
      <Tabla etiqueta="Familias de la entrada" cargando={cargando} filas={datos?.filas} vacio={vacio}
             clave={(l) => `${l.alumno}-${l.apoderado}-${l.parentesco}`}
             columnas={[
               { id: 'alumno', titulo: 'Alumno', celda: (l) => l.alumno },
               { id: 'apoderado', titulo: 'Apoderado', celda: (l) => (
                 <>
                   {l.apoderado}
                   <span className="segunda-linea">{[l.parentesco, !l.con_app && 'sin la app'].filter(Boolean).join(' · ')}</span>
                 </>
               ) },
               { id: 'vio', titulo: 'Vio', nowrap: true, celda: (l) => (l.visto_en
                 ? <span className="tenue">{fechaHoraTabla(l.visto_en)}</span> : <Insignia tono="neutro">No</Insignia>) },
               e.pide_firma && { id: 'firma', titulo: firma, nowrap: true, celda: (l) => (l.firmado_en
                 ? <Insignia tono="bien">{fechaHoraTabla(l.firmado_en)}</Insignia> : <Insignia tono="tarde">Pendiente</Insignia>) },
             ].filter(Boolean)} />
      {paginacion && paginacion.total > 0 && <Paginacion {...paginacion} />}
    </section>
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
  categoria_id: '', programar: false, programado_para: '',
}

// Ahora en Lima, como valor de un datetime-local (para el mínimo del programado).
function ahoraLocal(minutos = 0) {
  const d = new Date(Date.now() + minutos * 60000)
  return d.toLocaleString('sv-SE', { timeZone: 'America/Lima' }).slice(0, 16).replace(' ', 'T')
}

function Escribir() {
  const navegar = useNavigate()
  const [op, setOp] = useState(null)
  const [f, setF] = useState(VACIO)
  const [archivos, setArchivos] = useState([])
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [plantillas, setPlantillas] = useState([])
  const [categorias, setCategorias] = useState([])

  useEffect(() => {
    api('/api/configuracion/plantillas').then(setPlantillas).catch(() => {})
    api('/api/configuracion/categorias').then((l) => setCategorias(l.filter((c) => c.activa))).catch(() => {})
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
      categoria_id: f.tipo === 'incidencia' ? n(f.categoria_id) : null,
      programado_para: f.tipo === 'comunicado' && f.programar && f.programado_para ? conZonaLima(f.programado_para) : null,
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

      {f.tipo === 'comunicado' && plantillas.length > 0 && (
        <label>Plantilla
          <select value="" onChange={(ev) => {
            const p = plantillas.find((x) => String(x.id) === ev.target.value)
            if (p) setF({ ...f, titulo: p.titulo, cuerpo: p.cuerpo })
          }}>
            <option value="">Elegir una plantilla…</option>
            {plantillas.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
          </select>
        </label>
      )}
      {f.tipo === 'incidencia' && categorias.length > 0 && (
        <label>Categoría
          <select value={f.categoria_id} onChange={cambiar('categoria_id')} required>
            <option value="">Elige…</option>
            {[['merito', 'Méritos'], ['mejora', 'A mejorar']].map(([t, nombre]) => (
              <optgroup key={t} label={nombre}>
                {categorias.filter((c) => c.tipo === t).map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
      )}

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
      {f.tipo === 'comunicado' && (
        <div className="programar">
          <label className="check">
            <input type="checkbox" checked={f.programar} onChange={cambiar('programar')} />
            Programar el envío
          </label>
          {f.programar && (
            <label>Sale el (hora de Lima)
              <input type="datetime-local" value={f.programado_para} onChange={cambiar('programado_para')}
                     min={ahoraLocal(2)} max={ahoraLocal(90 * 24 * 60)} required />
            </label>
          )}
        </div>
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
        {f.tipo === 'comunicado' && f.programar
          ? 'Las familias lo verán y recibirán el aviso a la hora elegida. Puedes cancelarlo antes desde la bandeja.'
          : 'Las familias con la app reciben un aviso en el celular.'}
      </p>
      <button className="boton" disabled={enviando}>
        {enviando ? 'Enviando…' : f.tipo === 'comunicado' && f.programar ? 'Programar' : 'Enviar'}
      </button>
    </form>
  )
}

function Opcion({ valor, onChange, lista, nombre }) {
  return (
    <label>{nombre}
      <select value={valor} onChange={onChange} required>
        <option value="">Elige…</option>
        {lista.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
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
          {secciones.map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
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
      <Tabla etiqueta="Docentes por sección" filas={datos.secciones}
             vacio={{ icono: Users, titulo: 'No hay secciones en el año activo', texto: 'Créalas en Padrón › Secciones.' }}
             columnas={[
               { id: 'seccion', titulo: 'Sección', ancho: '30%', celda: (s) => s.nombre },
               { id: 'docentes', titulo: 'A cargo', celda: (s) => (
                 <span className="chips">
                   {s.docentes.map((d) => (
                     <span key={d} className="chip">{nombres[d] || d}
                       <button className="enlace" aria-label={`Quitar a ${nombres[d] || d}`} onClick={() => guardar(s, s.docentes.filter((x) => x !== d))}>×</button>
                     </span>
                   ))}
                   <select value="" aria-label={`Agregar docente a ${s.nombre}`} onChange={(e) => e.target.value && guardar(s, [...s.docentes, Number(e.target.value)])}>
                     <option value="">+ Agregar…</option>
                     {datos.personal.filter((p) => !s.docentes.includes(p.id)).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
                   </select>
                 </span>
               ) },
             ]} />
    </>
  )
}
