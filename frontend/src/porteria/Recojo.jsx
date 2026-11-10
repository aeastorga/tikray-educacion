// Recojo seguro en la portería: al marcar la salida, quién puede recoger al alumno hoy (apoderados, autorizados
// y autorizados del día) y, al tocar a uno, queda registrado. Si quien recoge no está en la lista, no se bloquea
// la salida: se escribe su nombre y documento y queda "fuera de la lista". Funciona sin internet.
import { useEffect, useState } from 'react'
import { UserRound } from 'lucide-react'
import { leerToken } from '../api.js'
import '../espacios/recojo.css'

const TIPO = { apoderado: 'Apoderado', autorizado: 'Autorizado', del_dia: 'Solo hoy' }
const TIPOS_DOC = ['DNI', 'CE', 'PAS', 'OTRO']

// Foto del autorizado: se pide con la sesión (no es pública). Sin internet, solo las iniciales.
function Foto({ persona }) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    if (!persona.foto || persona.tipo !== 'autorizado' || !navigator.onLine) return undefined
    let vivo = true
    let creada = null
    const token = leerToken()
    fetch(`/api/recojo/autorizados/${persona.id}/foto`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b && vivo) { creada = URL.createObjectURL(b); setUrl(creada) } })
      .catch(() => {})
    return () => { vivo = false; if (creada) URL.revokeObjectURL(creada) }
  }, [persona])
  return url
    ? <img className="recojo-foto" src={url} alt={`Foto de ${persona.nombre}`} />
    : <span className="recojo-foto sin-foto" aria-hidden="true"><UserRound size={28} /></span>
}

export function nombreElegido(e) {
  return e ? e.nombre : null
}

export default function Recojo({ alumno, lista, elegido, alElegir }) {
  const [otro, setOtro] = useState(null)
  const [cambiando, setCambiando] = useState(false)
  const personas = lista?.personas || []
  const primerNombre = alumno.nombre.split(', ')[1]?.split(' ')[0] || alumno.nombre

  if (elegido && !cambiando) {
    return (
      <section className={`recojo-panel elegido${elegido.fuera_de_lista ? ' fuera' : ''}`} aria-live="polite">
        <div>
          <b>Recogido por {elegido.nombre}</b>
          {elegido.fuera_de_lista && <span className="recojo-fuera">Fuera de la lista: la familia lo verá en la app</span>}
        </div>
        <button type="button" className="enlace" onClick={() => setCambiando(true)}>Cambiar</button>
      </section>
    )
  }

  function elegir(e) {
    setCambiando(false)
    setOtro(null)
    alElegir(e)
  }

  function enviarOtro(ev) {
    ev.preventDefault()
    elegir({ tipo: 'otro', nombres: otro.nombres.trim(), apellidos: otro.apellidos.trim(),
      tipo_documento: otro.tipo_documento, numero_documento: otro.numero_documento.trim(),
      nombre: `${otro.nombres.trim()} ${otro.apellidos.trim()}`, fuera_de_lista: true })
  }

  return (
    <section className="recojo-panel" aria-labelledby="t-recojo">
      <h3 id="t-recojo">¿Quién recoge a {primerNombre}?</h3>
      <p className="tenue">Opcional: compara con su documento y toca a la persona. La salida ya quedó registrada.</p>
      {personas.length === 0 && <p className="tenue">No hay nadie en la lista.</p>}
      <ul className="recojo-lista">
        {personas.map((p) => (
          <li key={`${p.tipo}-${p.id}`}>
            <button type="button" className="recojo-persona"
                    onClick={() => elegir({ tipo: p.tipo, persona_id: p.id, nombre: p.nombre, fuera_de_lista: false })}>
              <Foto persona={p} />
              <span className="recojo-datos">
                <b>{p.nombre}</b>
                <span>{p.parentesco} · {p.tipo_documento} {p.documento}</span>
                <span className={`recojo-tipo ${p.tipo}`}>{TIPO[p.tipo]}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {!otro && (
        <button type="button" className="boton secundario" onClick={() => setOtro({ nombres: '', apellidos: '', tipo_documento: 'DNI', numero_documento: '' })}>
          Otra persona (no está en la lista)
        </button>
      )}
      {otro && (
        <form className="recojo-otro" onSubmit={enviarOtro}>
          <p className="recojo-fuera">No está en la lista: se registra igual y la familia lo verá en la app.</p>
          <div className="recojo-campos">
            <label>Nombres<input required value={otro.nombres} onChange={(e) => setOtro({ ...otro, nombres: e.target.value })} /></label>
            <label>Apellidos<input required value={otro.apellidos} onChange={(e) => setOtro({ ...otro, apellidos: e.target.value })} /></label>
            <label>Documento
              <select value={otro.tipo_documento} onChange={(e) => setOtro({ ...otro, tipo_documento: e.target.value })}>
                {TIPOS_DOC.map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            <label>Número<input required inputMode={otro.tipo_documento === 'DNI' ? 'numeric' : 'text'}
                                 pattern={otro.tipo_documento === 'DNI' ? '[0-9]{8}' : '[A-Za-z0-9-]{1,15}'}
                                 title={otro.tipo_documento === 'DNI' ? '8 dígitos' : 'Hasta 15 letras o números'}
                                 value={otro.numero_documento} onChange={(e) => setOtro({ ...otro, numero_documento: e.target.value })} /></label>
          </div>
          <div className="acciones">
            <button className="boton">Registrar quién lo recoge</button>
            <button type="button" className="enlace" onClick={() => setOtro(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {cambiando && <button type="button" className="enlace" onClick={() => setCambiando(false)}>Dejar como estaba</button>}
    </section>
  )
}
