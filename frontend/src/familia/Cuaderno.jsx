import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Check, MessageCircle, NotebookPen, Paperclip } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api.js'
import { Adjuntos, Categoria, Detalles, fechaHora, TIPOS } from '../espacios/Cuaderno.jsx'
import '../espacios/cuaderno.css'
import { CampoArchivo, Mensaje, Vacio } from '../espacios/comun/index.js'

// Lo que dice el botón de firma según el tipo.
const BOTON_FIRMA = { comunicado: 'Firmar: leí el comunicado', incidencia: 'Enterado', citacion: 'Confirmo que asistiré' }
const FIRMADO = { comunicado: 'Firmaste', incidencia: 'Marcaste enterado', citacion: 'Confirmaste' }

function hoyLima() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Lima' })
}

// --- En el inicio: lo último del cuaderno --------------------------------------------------

export function ListaCuaderno({ recargar }) {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const [todo, setTodo] = useState(false)

  useEffect(() => {
    api('/api/familia/cuaderno').then(setDatos).catch((e) => setError(e.estado === 403 ? null : e.message))
  }, [recargar])

  if (error) return <Mensaje tipo="error">{error}</Mensaje>
  if (!datos) return null
  const porFirmar = datos.entradas.filter((e) => e.pide_firma && !e.firmado_en)
  const visibles = todo ? datos.entradas : datos.entradas.slice(0, 8)
  return (
    <section className="cuaderno-familia">
      <h2>Cuaderno de control</h2>
      {porFirmar.length > 0 && (
        <p className="aviso">Tienes {porFirmar.length === 1 ? '1 pendiente de firmar' : `${porFirmar.length} pendientes de firmar`}.</p>
      )}
      {datos.hijos.length > 0 && (
        <div className="acciones-familia">
          <Link className="boton secundario" to="/familia/cuaderno/nuevo/justificacion">Justificar una falta</Link>
          <Link className="boton secundario" to="/familia/cuaderno/nuevo/permiso">Pedir permiso de salida</Link>
        </div>
      )}
      {datos.entradas.length === 0 ? <Vacio icono={NotebookPen} titulo="Aún no hay nada en el cuaderno" texto="Aquí llegan los comunicados del colegio. Use los botones de arriba para justificar una falta o pedir un permiso." /> : (
        <ul className="lista-cuaderno">
          {visibles.map((e) => (
            <li key={e.id} className={[!e.visto || (e.pide_firma && !e.firmado_en) ? 'nueva' : '',
              e.categoria?.tipo === 'merito' ? 'merito' : ''].join(' ').trim()}>
              <Link to={`/familia/cuaderno/${e.id}`}>
                <span className={`tipo-cuaderno ${e.tipo}`}>{TIPOS[e.tipo]}</span>
                <Categoria c={e.categoria} />
                <b> {e.titulo}</b>
                <span className="tenue pequeno">
                  {' '}· {e.alumnos.join(', ')} · {fechaHora(e.creado_en)}
                  {e.estado && ` · ${e.estado === 'pendiente' ? 'por aprobar' : e.estado}`}
                  {e.pide_firma && !e.firmado_en && ' · falta tu firma'}
                  {e.respuestas > 0 && <span className="icono-texto"> · <MessageCircle size={14} aria-label="respuestas" /> {e.respuestas}</span>}
                  {e.adjuntos > 0 && <span className="icono-texto"> · <Paperclip size={14} aria-label="adjuntos" /> {e.adjuntos}</span>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {!todo && datos.entradas.length > 8 && <button className="enlace" onClick={() => setTodo(true)}>Ver todo</button>}
    </section>
  )
}

// --- Una entrada: leer, firmar, responder ---------------------------------------------------

export function DetalleCuaderno() {
  const { id } = useParams()
  const [e, setE] = useState(null)
  const [error, setError] = useState(null)
  const [respuesta, setRespuesta] = useState('')
  const [enviando, setEnviando] = useState(false)

  const cargar = useCallback(() => api(`/api/familia/cuaderno/${id}`).then(setE).catch((err) => setError(err.message)), [id])
  useEffect(() => { cargar() }, [cargar])

  async function firmar() {
    setEnviando(true)
    try { await api(`/api/familia/cuaderno/${id}/firmar`, { metodo: 'POST' }); cargar() }
    catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  async function responder(ev) {
    ev.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      await api(`/api/familia/cuaderno/${id}/respuestas`, { metodo: 'POST', datos: { cuerpo: respuesta } })
      setRespuesta('')
      cargar()
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  return (
    <main className="familia-contenido cuaderno-detalle">
      <Link to="/familia/cuaderno" className="enlace acceso-volver"><ArrowLeft size={18} aria-hidden="true" /> Volver</Link>
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      {e && <>
        <p className="tenue">
          <span className={`tipo-cuaderno ${e.tipo}`}>{TIPOS[e.tipo]}</span> <Categoria c={e.categoria} />
          {' '}{e.alumnos.join(', ')} · {fechaHora(e.creado_en)}
          {e.autor && ` · ${e.autor}`}
        </p>
        {e.categoria?.tipo === 'merito' && <p className="merito-destacado">¡Un mérito para {e.alumnos.join(', ')}!</p>}
        <h2>{e.titulo}</h2>
        <Detalles e={e} />
        {e.cuerpo && <p className="cuaderno-cuerpo">{e.cuerpo}</p>}
        <Adjuntos lista={e.adjuntos} ruta="/api/familia/cuaderno/adjuntos" />
        {e.pide_firma && (e.firmado_en
          ? <p className="firmado icono-texto"><Check size={18} aria-hidden="true" /> {FIRMADO[e.tipo]} el {fechaHora(e.firmado_en)}</p>
          : <button className="boton grande" disabled={enviando} onClick={firmar}>{BOTON_FIRMA[e.tipo]}</button>)}
        {e.tipo === 'citacion' && !e.firmado_en && (
          <p className="tenue pequeno">¿No puedes asistir? Respóndele al colegio aquí abajo.</p>
        )}

        <h3>Respuestas</h3>
        {e.mensajes.length === 0 && <p className="tenue">Aún no hay respuestas.</p>}
        <ul className="hilo">
          {e.mensajes.map((m) => (
            <li key={m.id} className={m.de_familia ? 'del-colegio' : 'de-familia'}>
              <span className="tenue pequeno">{m.autor} · {fechaHora(m.creado_en)}</span>
              <p>{m.cuerpo}</p>
            </li>
          ))}
        </ul>
        <form className="fila-form" onSubmit={responder}>
          <textarea aria-label="Escribe al colegio" value={respuesta} required maxLength={4000} rows={2} placeholder="Escribe al colegio"
                    onChange={(ev) => setRespuesta(ev.target.value)} />
          <button className="boton" disabled={enviando}>Enviar</button>
        </form>
      </>}
    </main>
  )
}

// --- Lo que pide el padre: justificación o permiso de salida ----------------------------------

export function PedidoCuaderno() {
  const { tipo } = useParams()
  const navegar = useNavigate()
  const justificacion = tipo === 'justificacion'
  const [hijos, setHijos] = useState(null)
  const [f, setF] = useState({ alumno_id: '', desde: hoyLima(), hasta: '', motivo: '', detalle: '', hora: '', recoge: '' })
  const [archivos, setArchivos] = useState([])
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    api('/api/familia/cuaderno').then((d) => {
      setHijos(d.hijos)
      if (d.hijos.length === 1) setF((x) => ({ ...x, alumno_id: String(d.hijos[0].id) }))
    }).catch((e) => setError(e.message))
  }, [])

  const cambiar = (campo) => (ev) => setF({ ...f, [campo]: ev.target.value })

  async function enviar(ev) {
    ev.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      let r
      if (justificacion) {
        const formulario = new FormData()
        formulario.append('datos', JSON.stringify({ alumno_id: Number(f.alumno_id), desde: f.desde,
          hasta: f.hasta || null, motivo: f.motivo, detalle: f.detalle }))
        for (const a of archivos) formulario.append('archivos', a)
        r = await api('/api/familia/cuaderno/justificaciones', { metodo: 'POST', formulario })
      } else {
        r = await api('/api/familia/cuaderno/permisos-salida', { metodo: 'POST', datos: {
          alumno_id: Number(f.alumno_id), fecha: f.desde, hora: f.hora, recoge: f.recoge, motivo: f.motivo } })
      }
      navegar(`/familia/cuaderno/${r.id}`, { replace: true })
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  return (
    <main className="familia-contenido">
      <Link to="/familia/cuaderno" className="enlace acceso-volver"><ArrowLeft size={18} aria-hidden="true" /> Volver</Link>
      <form className="tarjeta ancho" onSubmit={enviar}>
        <h2>{justificacion ? 'Justificar una falta' : 'Pedir permiso de salida'}</h2>
        {hijos && hijos.length > 1 && (
          <label>Hijo o hija
            <select value={f.alumno_id} onChange={cambiar('alumno_id')} required>
              <option value="">Elige…</option>
              {hijos.map((h) => <option key={h.id} value={h.id}>{h.nombres}</option>)}
            </select>
          </label>
        )}
        {justificacion ? (
          <div className="fila-form sin-margen">
            <label>Desde<input type="date" value={f.desde} onChange={cambiar('desde')} required max={hoyLima()} /></label>
            <label>Hasta (si fue más de un día)<input type="date" value={f.hasta} onChange={cambiar('hasta')} min={f.desde} /></label>
          </div>
        ) : (
          <div className="fila-form sin-margen">
            <label>Día<input type="date" value={f.desde} onChange={cambiar('desde')} required min={hoyLima()} /></label>
            <label>Hora de salida<input type="time" value={f.hora} onChange={cambiar('hora')} required /></label>
          </div>
        )}
        <label>Motivo
          <input value={f.motivo} onChange={cambiar('motivo')} required maxLength={200}
                 placeholder={justificacion ? 'Por ejemplo: estuvo con fiebre' : 'Por ejemplo: cita médica'} />
        </label>
        {justificacion ? <>
          <label>Detalle (opcional)
            <textarea value={f.detalle} onChange={cambiar('detalle')} rows={3} maxLength={4000} />
          </label>
          <label>Certificado o constancia (opcional; foto o PDF)
            <CampoArchivo multiple accept=".pdf,.jpg,.jpeg,.png,.webp"
                   onChange={(ev) => setArchivos([...ev.target.files].slice(0, 5))} />
          </label>
        </> : (
          <label>¿Quién lo recoge? (nombre y DNI)
            <input value={f.recoge} onChange={cambiar('recoge')} required maxLength={120} />
          </label>
        )}
        {error && <Mensaje tipo="error">{error}</Mensaje>}
        <p className="tenue pequeno">
          {justificacion ? 'El colegio la revisará y te avisaremos cuando la apruebe.'
            : 'La portería verá el permiso al momento de la salida. Te avisaremos cuando el colegio lo apruebe.'}
        </p>
        <button className="boton" disabled={enviando || !hijos}>Enviar</button>
      </form>
    </main>
  )
}
