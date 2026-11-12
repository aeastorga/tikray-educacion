// Autorizaciones del panel (permiso "autorizaciones"): el colegio pide permiso a las familias para algo puntual y
// cada apoderado responde por cada hijo. Lista con conteos, formulario (borrador → publicar), seguimiento por sección
// con quién respondió y cuándo, "Recordar a los que faltan", cerrar, anular con motivo y la lista en PDF y Excel.
// Un rol con "solo sus secciones" solo ve y crea para sus secciones.
import { FileDown, FileSpreadsheet, Paperclip, Plus, Send, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, descargar } from '../api.js'
import { CampoArchivo, Cargando, Cifras, Encabezado, Insignia, Mensaje, Tabla, fechaCorta, fechaHora, plural } from './comun/index.js'
import './autorizaciones.css'

const ESTADOS = { borrador: ['Borrador', 'neutro'], publicada: ['Abierta', 'info'], cerrada: ['Cerrada', 'neutro'],
  anulada: ['Anulada', 'falta'] }
const RESPUESTA = { autoriza: ['Autoriza', 'bien'], no_autoriza: ['No autoriza', 'falta'], sin_respuesta: ['Sin respuesta', 'neutro'] }
const VACIO = { titulo: '', descripcion: '', fecha_actividad: '', fecha_limite: '', alcance: 'colegio', niveles: [],
  secciones: [], alumnos: [] }

export default function Autorizaciones({ editar }) {
  return (
    <section className="autorizaciones">
      <Routes>
        <Route index element={<Lista editar={editar} />} />
        <Route path="nueva" element={<Formulario />} />
        <Route path=":id" element={<Detalle editar={editar} />} />
        <Route path=":id/editar" element={<Formulario />} />
      </Routes>
    </section>
  )
}

function Estado({ estado }) {
  const [texto, tono] = ESTADOS[estado] || [estado, 'neutro']
  return <Insignia tono={tono}>{texto}</Insignia>
}

function Barra({ conteo, estado }) {
  const { total, autorizan, no_autorizan: no } = conteo
  if (!total) return <span className="tenue">Sin alumnos</span>
  if (estado === 'borrador') return <span className="tenue">Sin publicar · {plural(total, 'alumno', 'alumnos')}</span>
  const pct = (n) => `${(n / total) * 100}%`
  return (
    <div className="barra-respuestas" title={`${autorizan} autorizan, ${no} no, ${total - autorizan - no} faltan`}>
      <div className="barra-pista" aria-hidden="true">
        <span className="si" style={{ width: pct(autorizan) }} />
        <span className="no" style={{ width: pct(no) }} />
      </div>
      <small>{autorizan} sí · {no} no · {total - autorizan - no} faltan</small>
    </div>
  )
}

function Lista({ editar }) {
  const ir = useNavigate()
  const [filas, setFilas] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { api('/api/autorizaciones').then(setFilas).catch((e) => setError(e.message)) }, [])
  return (
    <>
      <Encabezado titulo="Autorizaciones"
        descripcion="Pida permiso a las familias para un paseo, el uso de fotos o una actividad. Cada apoderado responde por cada hijo desde la app."
        acciones={editar && (
          <button type="button" className="boton" onClick={() => ir('/panel/autorizaciones/nueva')}>
            <Plus size={18} aria-hidden="true" /> Nueva autorización</button>)} />
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      <Tabla etiqueta="Autorizaciones" cargando={!filas && !error} filas={filas || []}
        alFila={(a) => ir(`/panel/autorizaciones/${a.id}`)}
        vacio={{ icono: ShieldCheck, titulo: 'Aún no hay autorizaciones',
          texto: editar ? 'Cree la primera: se guarda como borrador hasta que la publique.' : 'Cuando el colegio publique una, aparecerá aquí.' }}
        columnas={[
          { id: 'titulo', titulo: 'Autorización', celda: (a) => <><b>{a.titulo}</b><span className="segunda-linea">{a.para}</span></> },
          { id: 'limite', titulo: 'Fecha límite', nowrap: true, celda: (a) => fechaCorta(a.fecha_limite) },
          { id: 'estado', titulo: 'Estado', celda: (a) => <Estado estado={a.estado} /> },
          { id: 'respuestas', titulo: 'Respuestas', ancho: '30%', celda: (a) => <Barra conteo={a.conteo} estado={a.estado} /> },
        ]} />
    </>
  )
}

function Formulario() {
  const { id } = useParams()
  const ir = useNavigate()
  const [opciones, setOpciones] = useState(null)
  const [form, setForm] = useState(id ? null : VACIO)
  const [publicada, setPublicada] = useState(false)
  const [archivo, setArchivo] = useState(null)
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  useEffect(() => { api('/api/autorizaciones/opciones').then(setOpciones).catch((e) => setError(e.message)) }, [])
  useEffect(() => {
    if (!id) return
    api(`/api/autorizaciones/${id}`).then((a) => {
      setPublicada(a.estado !== 'borrador')
      const nombres = Object.fromEntries(a.por_seccion.flatMap((s) => s.alumnos.map((x) => [x.alumno_id, x.alumno])))
      setForm({ ...VACIO, ...a, descripcion: a.descripcion || '', fecha_actividad: a.fecha_actividad || '',
        niveles: a.niveles, secciones: a.secciones, alumnos: a.alumnos.map((x) => ({ id: x, nombre: nombres[x] || `Alumno ${x}` })) })
    }).catch((e) => setError(e.message))
  }, [id])
  if (error && !form) return <Mensaje tipo="error">{error}</Mensaje>
  if (!form || !opciones) return <Cargando />

  const set = (k, v) => setForm({ ...form, [k]: v })
  const alternar = (k, x) => set(k, form[k].includes(x) ? form[k].filter((y) => y !== x) : [...form[k], x])
  const alcances = [['colegio', 'Todo el colegio'], ['niveles', 'Uno o varios niveles'], ['secciones', 'Una o varias secciones'],
    ['alumnos', 'Alumnos sueltos']].filter(([v]) => !opciones.solo_sus_secciones || ['secciones', 'alumnos'].includes(v))

  async function guardar(publicar) {
    setError(null)
    setEnviando(true)
    const datos = { titulo: form.titulo, descripcion: form.descripcion || null, fecha_actividad: form.fecha_actividad || null,
      fecha_limite: form.fecha_limite, alcance: form.alcance, niveles: form.niveles, secciones: form.secciones,
      alumnos: form.alumnos.map((x) => x.id) }
    try {
      const a = id ? await api(`/api/autorizaciones/${id}`, { metodo: 'PUT', datos })
        : await api('/api/autorizaciones', { metodo: 'POST', datos })
      if (archivo) await api(`/api/autorizaciones/${a.id}/adjunto`, { metodo: 'PUT', archivo })
      if (publicar) await api(`/api/autorizaciones/${a.id}/publicar`, { metodo: 'POST' })
      ir(`/panel/autorizaciones/${a.id}`)
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  const porNivel = opciones.niveles.length
    ? opciones.niveles.map((n) => ({ ...n, secciones: opciones.secciones.filter((s) => s.nivel_id === n.id) }))
    : [{ id: 0, nombre: 'Sus secciones', secciones: opciones.secciones }]
  return (
    <>
      <Encabezado titulo={id ? 'Editar autorización' : 'Nueva autorización'}
        descripcion={publicada ? 'Ya está publicada: puede cambiar los textos, las fechas y el adjunto, no a quién va.'
          : 'Se guarda como borrador. Las familias la reciben cuando la publique.'} />
      <form className="tarjeta-panel form-autorizacion" onSubmit={(e) => { e.preventDefault(); guardar(false) }}>
        <label>Título
          <input required maxLength={120} value={form.titulo} onChange={(e) => set('titulo', e.target.value)}
                 placeholder="Paseo al Parque de las Leyendas" />
        </label>
        <label>Descripción (opcional)
          <textarea maxLength={2000} rows={4} value={form.descripcion} onChange={(e) => set('descripcion', e.target.value)}
                    placeholder="Lugar, horario, qué traer y, si tiene costo, cuánto y cómo se paga." />
        </label>
        <div className="fila-form">
          <label>Fecha de la actividad (opcional)
            <input type="date" value={form.fecha_actividad} onChange={(e) => set('fecha_actividad', e.target.value)} />
          </label>
          <label>Responder hasta
            <input type="date" required value={form.fecha_limite} min={opciones.hoy}
                   max={form.fecha_actividad || undefined} onChange={(e) => set('fecha_limite', e.target.value)} />
          </label>
        </div>
        <fieldset disabled={publicada}>
          <legend>¿A quién va?</legend>
          <div className="opciones-para">
            {alcances.map(([v, t]) => (
              <label key={v}><input type="radio" name="alcance" value={v} checked={form.alcance === v}
                                    onChange={() => set('alcance', v)} /> {t}</label>
            ))}
          </div>
          {form.alcance === 'niveles' && (
            <div className="destinos">
              {opciones.niveles.map((n) => (
                <label key={n.id}><input type="checkbox" checked={form.niveles.includes(n.id)} onChange={() => alternar('niveles', n.id)} /> {n.nombre}</label>
              ))}
            </div>
          )}
          {form.alcance === 'secciones' && (
            <div className="destinos">
              {opciones.secciones.length === 0 && <p className="tenue">No hay secciones disponibles en el año escolar activo.</p>}
              {porNivel.filter((n) => n.secciones.length).map((n) => (
                <div key={n.id} style={{ display: 'contents' }}>
                  <h5>{n.nombre}</h5>
                  {n.secciones.map((s) => (
                    <label key={s.id}><input type="checkbox" checked={form.secciones.includes(s.id)} onChange={() => alternar('secciones', s.id)} /> {s.nombre}</label>
                  ))}
                </div>
              ))}
            </div>
          )}
          {form.alcance === 'alumnos' && <ElegirAlumnos elegidos={form.alumnos} cambiar={(v) => set('alumnos', v)} />}
        </fieldset>
        <label>Adjunto (opcional, PDF o imagen de hasta 5 MB)
          <CampoArchivo accept="application/pdf,image/jpeg,image/png,image/webp"
                 onChange={(e) => setArchivo(e.target.files[0] || null)} />
          {form.adjunto && !archivo && <small className="tenue">Actual: {form.adjunto.nombre}. Si elige otro, lo reemplaza.</small>}
        </label>
        <p className="tenue">Si la actividad tiene costo, indíquelo en la descripción.</p>
        <div className="acciones">
          {!publicada && <button type="button" className="boton" disabled={enviando} onClick={() => guardar(true)}>
            <Send size={18} aria-hidden="true" /> Publicar</button>}
          <button type="button" className={publicada ? 'boton' : 'boton secundario'} disabled={enviando} onClick={() => guardar(false)}>
            {publicada ? 'Guardar cambios' : 'Guardar borrador'}</button>
          <button type="button" className="enlace" onClick={() => ir(id ? `/panel/autorizaciones/${id}` : '/panel/autorizaciones')}>Cancelar</button>
        </div>
        {error && <Mensaje tipo="error">{error}</Mensaje>}
      </form>
    </>
  )
}

function ElegirAlumnos({ elegidos, cambiar }) {
  const [q, setQ] = useState('')
  const [encontrados, setEncontrados] = useState([])
  useEffect(() => {
    if (q.trim().length < 2) { setEncontrados([]); return undefined }
    const t = setTimeout(() => {
      api(`/api/autorizaciones/alumnos?q=${encodeURIComponent(q.trim())}`).then(setEncontrados).catch(() => setEncontrados([]))
    }, 250)
    return () => clearTimeout(t)
  }, [q])
  const ids = elegidos.map((x) => x.id)
  return (
    <div className="elegir-alumnos">
      {elegidos.length > 0 && (
        <ul className="chips" aria-label="Alumnos elegidos">
          {elegidos.map((x) => (
            <li key={x.id}>{x.nombre}
              <button type="button" aria-label={`Quitar a ${x.nombre}`} onClick={() => cambiar(elegidos.filter((y) => y.id !== x.id))}>×</button>
            </li>
          ))}
        </ul>
      )}
      <label>Buscar alumno
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Apellido, nombre o DNI" />
      </label>
      {encontrados.length > 0 && (
        <ul className="resultados-alumnos">
          {encontrados.filter((x) => !ids.includes(x.id)).map((x) => (
            <li key={x.id}>
              <button type="button" className="enlace" onClick={() => { cambiar([...elegidos, { id: x.id, nombre: x.nombre }]); setQ('') }}>
                {x.nombre}</button> <small className="tenue">{x.seccion}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Detalle({ editar }) {
  const { id } = useParams()
  const ir = useNavigate()
  const [a, setA] = useState(null)
  const [error, setError] = useState(null)
  const [mensaje, setMensaje] = useState(null)
  const [anulando, setAnulando] = useState(false)
  const cargar = useCallback(() => {
    api(`/api/autorizaciones/${id}`).then(setA).catch((e) => setError(e.message))
  }, [id])
  useEffect(() => { cargar() }, [cargar])

  async function accion(ruta, texto, datos) {
    setError(null)
    setMensaje(null)
    try {
      const r = await api(`/api/autorizaciones/${id}/${ruta}`, { metodo: 'POST', datos })
      setMensaje(texto(r))
      setAnulando(false)
      cargar()
    } catch (e) { setError(e.message) }
  }
  async function bajar(ext, seccion) {
    setError(null)
    const q = seccion ? `?seccion_id=${seccion}` : ''
    try { await descargar(`/api/autorizaciones/${id}/lista.${ext}${q}`, `autorizacion-${id}.${ext}`) } catch (e) { setError(e.message) }
  }
  async function verAdjunto() {
    try { await descargar(`/api/autorizaciones/${id}/adjunto`, a.adjunto.nombre) } catch (e) { setError(e.message) }
  }

  if (error && !a) return <Mensaje tipo="error">{error}</Mensaje>
  if (!a) return <Cargando />
  const abierta = a.estado === 'publicada'
  const avisos = (r) => `${plural(r.avisos, 'familia', 'familias')}`
  return (
    <>
      <button type="button" className="enlace volver" onClick={() => ir('/panel/autorizaciones')}>← Autorizaciones</button>
      <Encabezado titulo={a.titulo} acciones={<Estado estado={a.estado} />} />
      <div className="tarjeta-panel detalle-autorizacion">
        <dl className="datos-autorizacion">
          <div><dt>Para</dt><dd>{a.para}</dd></div>
          {a.fecha_actividad && <div><dt>Actividad</dt><dd>{fechaCorta(a.fecha_actividad)}</dd></div>}
          <div><dt>Responder hasta</dt><dd>{fechaCorta(a.fecha_limite)}</dd></div>
          {a.publicada_en && <div><dt>Publicada</dt><dd>{fechaHora(a.publicada_en)}</dd></div>}
        </dl>
        {a.descripcion && <p className="descripcion">{a.descripcion}</p>}
        {a.adjunto && <button type="button" className="enlace icono-texto" onClick={verAdjunto}>
          <Paperclip size={16} aria-hidden="true" /> {a.adjunto.nombre}</button>}
        {a.estado === 'anulada' && <p className="aviso-anulada">Anulada: {a.anulado_motivo}</p>}
      </div>
      {editar && a.estado !== 'anulada' && (
        <div className="acciones barra-acciones">
          {a.estado === 'borrador' && <button type="button" className="boton"
            onClick={() => accion('publicar', (r) => `Publicada. Se avisó a ${avisos(r)}.`)}><Send size={18} aria-hidden="true" /> Publicar</button>}
          {abierta && <button type="button" className="boton"
            onClick={() => accion('recordar', (r) => `Recordatorio enviado a ${avisos(r)}.`)}>Recordar a los que faltan</button>}
          {(a.estado === 'borrador' || abierta) && <button type="button" className="boton secundario"
            onClick={() => ir(`/panel/autorizaciones/${id}/editar`)}>Editar</button>}
          {abierta && <button type="button" className="boton secundario"
            onClick={() => accion('cerrar', () => 'Cerrada: ya no se puede responder.')}>Cerrar</button>}
          <button type="button" className="enlace" onClick={() => setAnulando(true)}>Anular</button>
        </div>
      )}
      {anulando && <Anular anular={(motivo) => accion('anular', () => 'Anulada. Sigue visible como anulada.', { motivo })}
                           cancelar={() => setAnulando(false)} />}
      <Mensaje tipo="ok">{mensaje}</Mensaje>
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      {a.recordado_en && abierta && <p className="tenue">Último recordatorio: {fechaHora(a.recordado_en)}.</p>}

      <Cifras items={[
        { etiqueta: 'Autorizan', valor: a.conteo.autorizan, tono: 'bien' },
        { etiqueta: 'No autorizan', valor: a.conteo.no_autorizan, tono: 'falta' },
        { etiqueta: a.estado === 'borrador' ? 'Alumnos' : 'Faltan', valor: a.estado === 'borrador' ? a.conteo.total : a.conteo.faltan },
      ]} />
      {a.estado !== 'borrador' && (
        <>
          <div className="acciones barra-descargas">
            <button type="button" className="boton secundario" onClick={() => bajar('pdf')}><FileDown size={18} aria-hidden="true" /> Lista en PDF</button>
            <button type="button" className="boton secundario" onClick={() => bajar('xlsx')}><FileSpreadsheet size={18} aria-hidden="true" /> Lista en Excel</button>
          </div>
          {a.por_seccion.map((s) => (
            <section key={s.seccion_id ?? 'sin'} className="seccion-autorizacion">
              <header>
                <h3>{s.seccion}</h3>
                <small className="tenue">{s.conteo.autorizan} sí · {s.conteo.no_autorizan} no · {s.conteo.faltan} faltan</small>
                {s.seccion_id && (
                  <span className="acciones">
                    <button type="button" className="enlace" aria-label={`PDF de ${s.seccion}`} onClick={() => bajar('pdf', s.seccion_id)}>PDF</button>
                    <button type="button" className="enlace" aria-label={`Excel de ${s.seccion}`} onClick={() => bajar('xlsx', s.seccion_id)}>Excel</button>
                  </span>
                )}
              </header>
              <Tabla etiqueta={`Respuestas de ${s.seccion}`} filas={s.alumnos} clave={(f) => f.alumno_id}
                columnas={[
                  { id: 'alumno', titulo: 'Alumno', celda: (f) => f.alumno },
                  { id: 'respuesta', titulo: 'Respuesta', celda: (f) => {
                    const [t, tono] = RESPUESTA[f.estado]
                    return <Insignia tono={tono}>{t}</Insignia>
                  } },
                  { id: 'quien', titulo: 'Respondió', vacio: (f) => !f.respuesta, celda: (f) => f.respuesta ? <Historial f={f} /> : '—' },
                  { id: 'comentario', titulo: 'Comentario', vacio: (f) => !f.respuesta?.comentario,
                    celda: (f) => f.respuesta?.comentario || '—' },
                ]} />
            </section>
          ))}
        </>
      )}
    </>
  )
}

function Historial({ f }) {
  const r = f.respuesta
  const antes = f.historial.slice(0, -1)
  return (
    <>
      {r.apoderado}<span className="segunda-linea">{fechaHora(r.en)}</span>
      {antes.length > 0 && (
        <details className="historial-respuestas">
          <summary>{plural(antes.length, 'cambio', 'cambios')}</summary>
          <ul>
            {antes.map((h) => (
              <li key={h.en}>{h.autoriza ? 'Autorizó' : 'No autorizó'}: {h.apoderado}, {fechaHora(h.en)}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

function Anular({ anular, cancelar }) {
  const [motivo, setMotivo] = useState('')
  return (
    <form className="tarjeta-panel form-anular" onSubmit={(e) => { e.preventDefault(); anular(motivo) }}>
      <label>Motivo de la anulación
        <input required maxLength={200} value={motivo} onChange={(e) => setMotivo(e.target.value)} autoFocus
               placeholder="Se suspende el paseo por lluvia…" />
      </label>
      <p className="tenue">Queda visible como anulada para el colegio y las familias, y no se mandan más recordatorios.</p>
      <div className="acciones">
        <button className="boton">Anular autorización</button>
        <button type="button" className="enlace" onClick={cancelar}>Cancelar</button>
      </div>
    </form>
  )
}
