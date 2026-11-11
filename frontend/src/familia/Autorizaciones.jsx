// Autorizaciones en la app de la familia: lo que el colegio pide autorizar, con las pendientes arriba. Por cada hijo,
// "Autorizo" o "No autorizo" y un comentario opcional. Se puede cambiar hasta la fecha límite; responde el apoderado
// que recibe los avisos de ese hijo.
import { Paperclip } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, descargar } from '../api.js'
import { fechaCorta, fechaHora } from '../espacios/comun/index.js'

export default function AutorizacionesFamilia() {
  const { yo } = useOutletContext()
  const [lista, setLista] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    if (yo?.estado !== 'activo' || yo?.modulos?.autorizaciones === false) return
    api('/api/familia/autorizaciones').then(setLista).catch((e) => setError(e.message))
  }, [yo])
  if (yo?.modulos?.autorizaciones === false) return <p className="tenue">El colegio no usa autorizaciones en la app.</p>
  if (yo && yo.estado !== 'activo') return <p className="tenue">Verá las autorizaciones cuando el colegio apruebe su cuenta.</p>
  const actualizar = (a) => setLista((l) => l.map((x) => (x.id === a.id ? a : x)))
  const pendientes = (lista || []).filter((a) => a.pendiente).length
  return (
    <>
      <div className="saludo"><h1>Autorizaciones</h1>
        <p className="tenue">{pendientes ? `Tiene ${pendientes === 1 ? '1 pendiente' : `${pendientes} pendientes`} por responder.`
          : 'Lo que el colegio le pide autorizar para sus hijos.'}</p>
      </div>
      {error && <p className="error">{error}</p>}
      {!lista && !error && <p className="tenue">Cargando…</p>}
      {lista?.length === 0 && <section className="tarjeta-app"><p className="tenue">No hay autorizaciones por ahora.</p></section>}
      <div className="lista-autorizaciones">
        {lista?.map((a) => <Tarjeta key={a.id} a={a} actualizar={actualizar} />)}
      </div>
    </>
  )
}

const ESTADO = { publicada: null, cerrada: 'Cerrada', anulada: 'Anulada' }

function Tarjeta({ a, actualizar }) {
  const [error, setError] = useState(null)
  async function adjunto() {
    setError(null)
    try { await descargar(`/api/familia/autorizaciones/${a.id}/adjunto`, a.adjunto.nombre) } catch (e) { setError(e.message) }
  }
  return (
    <article className={`tarjeta-app autorizacion-familia${a.pendiente ? ' pendiente' : ''}`}>
      <header>
        <h2>{a.titulo}</h2>
        {ESTADO[a.estado] && <span className={`chip-autorizacion ${a.estado}`}>{ESTADO[a.estado]}</span>}
        {a.pendiente && <span className="chip-autorizacion por-responder">Por responder</span>}
      </header>
      <p className="tenue fechas-autorizacion">
        {a.fecha_actividad && <>Actividad: {fechaCorta(a.fecha_actividad)} · </>}
        Responder hasta el {fechaCorta(a.fecha_limite)}
      </p>
      {a.descripcion && <p className="descripcion-autorizacion">{a.descripcion}</p>}
      {a.adjunto && <button type="button" className="enlace icono-texto" onClick={adjunto}>
        <Paperclip size={16} aria-hidden="true" /> {a.adjunto.nombre}</button>}
      {a.estado === 'anulada' && <p className="aviso-anulada-familia">El colegio la anuló: {a.anulado_motivo}</p>}
      {error && <p className="error">{error}</p>}
      <ul className="hijos-autorizacion">
        {a.hijos.map((h) => <Hijo key={h.alumno_id} a={a} h={h} actualizar={actualizar} />)}
      </ul>
    </article>
  )
}

function Hijo({ a, h, actualizar }) {
  const [cambiando, setCambiando] = useState(false)
  const [comentario, setComentario] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState(null)
  const r = h.respuesta
  async function responder(autoriza) {
    setError(null)
    setEnviando(true)
    try {
      actualizar(await api(`/api/familia/autorizaciones/${a.id}/respuestas`, { metodo: 'POST',
        datos: { alumno_id: h.alumno_id, autoriza, comentario: comentario || null } }))
      setCambiando(false)
      setComentario('')
    } catch (e) { setError(e.message) } finally { setEnviando(false) }
  }
  const pregunta = h.puede_responder && (!r || cambiando)
  return (
    <li>
      <div className="hijo-autorizacion">
        <b>{h.nombre}</b>
        {r ? (
          <span className={`respuesta-autorizacion ${r.autoriza ? 'si' : 'no'}`}>{r.autoriza ? 'Autorizado' : 'No autorizado'}</span>
        ) : <span className="respuesta-autorizacion sin">{a.estado === 'publicada' ? 'Sin responder' : 'Sin respuesta'}</span>}
      </div>
      {r && (
        <p className="tenue detalle-respuesta">
          {r.mia ? 'Usted respondió' : `Respondió ${r.apoderado}`} · {fechaHora(r.en)}
          {r.comentario && <> · “{r.comentario}”</>}
        </p>
      )}
      {pregunta && (
        <div className="responder-autorizacion">
          <label>Comentario (opcional)
            <input maxLength={300} value={comentario} onChange={(e) => setComentario(e.target.value)}
                   placeholder="Por ejemplo: lo recojo yo a la salida" />
          </label>
          <div className="botones-respuesta">
            <button type="button" className="boton" disabled={enviando} onClick={() => responder(true)}>Autorizo</button>
            <button type="button" className="boton secundario" disabled={enviando} onClick={() => responder(false)}>No autorizo</button>
          </div>
          {cambiando && <button type="button" className="enlace" onClick={() => setCambiando(false)}>Cancelar</button>}
        </div>
      )}
      {r && h.puede_responder && !cambiando && (
        <button type="button" className="enlace" onClick={() => setCambiando(true)}>Cambiar respuesta</button>
      )}
      {!h.puede_responder && a.estado === 'publicada' && (
        <p className="tenue detalle-respuesta">Responde el apoderado que recibe los avisos de {h.nombre}.</p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </li>
  )
}
