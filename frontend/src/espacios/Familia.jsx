import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, CLAVE_TOKEN_FAMILIA, guardarToken, leerToken } from '../api.js'
import { DetalleCuaderno, ListaCuaderno, PedidoCuaderno } from '../familia/Cuaderno.jsx'
import { crearPasskey, hayPasskeys, llaveVapid, usarPasskey } from '../familia/webauthn.js'
import Cabecera from './Cabecera.jsx'
import './familia.css'

const tokenFamilia = () => leerToken(CLAVE_TOKEN_FAMILIA)
const guardar = (t) => guardarToken(t, CLAVE_TOKEN_FAMILIA)

export default function Familia({ colegio }) {
  useLocation()  // al entrar o salir cambia la ruta: volver a leer el token
  return (
    <Routes>
      <Route index element={tokenFamilia() ? <Inicio colegio={colegio} /> : <Ingreso colegio={colegio} />} />
      <Route path="activar" element={<Activar colegio={colegio} />} />
      <Route path="cuaderno/nuevo/:tipo" element={<ConSesion colegio={colegio}><PedidoCuaderno /></ConSesion>} />
      <Route path="cuaderno/:id" element={<ConSesion colegio={colegio}><DetalleCuaderno /></ConSesion>} />
      <Route path="*" element={<Navigate to="/familia" replace />} />
    </Routes>
  )
}

// Pantallas del cuaderno: con sesión (si no, al ingreso) y la cabecera del colegio.
function ConSesion({ colegio, children }) {
  const navegar = useNavigate()
  useEffect(() => {
    const salir = () => navegar('/familia', { replace: true })
    window.addEventListener('sesion-familia-cerrada', salir)
    return () => window.removeEventListener('sesion-familia-cerrada', salir)
  }, [navegar])
  if (!tokenFamilia()) return <Navigate to="/familia" replace />
  return <div className="familia"><Cabecera colegio={colegio} />{children}</div>
}

// --- Ingreso: documento + PIN, o huella ------------------------------------------------

function Ingreso({ colegio }) {
  const navegar = useNavigate()
  const [documento, setDocumento] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)

  async function entrar(promesa) {
    setEnviando(true)
    setError(null)
    try {
      guardar((await promesa).token)
      navegar('/familia', { replace: true })
    } catch (err) {
      if (err.name !== 'NotAllowedError') setError(err.message)  // canceló la huella
    } finally {
      setEnviando(false)
    }
  }

  async function conPasskey() {
    const { opciones, reto } = await api('/api/familia/passkey/opciones-ingreso', { metodo: 'POST' })
    const credencial = await usarPasskey(opciones)
    return api('/api/familia/passkey/ingreso', { metodo: 'POST', datos: { credencial, reto } })
  }

  return (
    <main className="centro">
      <form className="tarjeta" onSubmit={(e) => {
        e.preventDefault()
        entrar(api('/api/familia/ingreso', { metodo: 'POST', datos: { documento, pin } }))
      }}>
        <Cabecera colegio={colegio} />
        {hayPasskeys() && (
          <button type="button" className="boton grande" disabled={enviando} onClick={() => entrar(conPasskey())}>
            Entrar con huella o rostro
          </button>
        )}
        <label>Tu DNI
          <input value={documento} onChange={(e) => setDocumento(e.target.value)} inputMode="numeric"
                 autoComplete="username" required />
        </label>
        <label>PIN (6 números)
          <input type="password" value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric"
                 maxLength={6} autoComplete="current-password" required />
        </label>
        {error && <p className="error">{error}</p>}
        <button className={hayPasskeys() ? 'boton secundario' : 'boton'} disabled={enviando}>Entrar con PIN</button>
        <p className="tenue pequeno">
          ¿Primera vez? Abre el enlace personal que te envió el colegio por WhatsApp.
          Si no lo tienes o olvidaste tu PIN, pide uno nuevo en secretaría.
        </p>
        <Link to="/" className="enlace">Volver</Link>
      </form>
    </main>
  )
}

// --- Activación con el enlace de un solo uso ---------------------------------------------

function Activar({ colegio }) {
  const navegar = useNavigate()
  // El token va después del #: no llega a los registros de ningún servidor.
  const [token] = useState(() => window.location.hash.slice(1))
  const [docs, setDocs] = useState({ documento_alumno: '', documento_apoderado: '' })
  const [revision, setRevision] = useState(null)
  const [acepto, setAcepto] = useState(false)
  const [pin, setPin] = useState({ actual: '', nuevo: '', repetir: '' })
  const [error, setError] = useState(null)
  const [fatal, setFatal] = useState(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    // Quita el token de la barra de direcciones (y del historial) apenas se lee.
    if (window.location.hash) history.replaceState(null, '', window.location.pathname)
  }, [])

  function fallo(err) {
    if (err.estado === 410 || err.estado === 404 || err.estado === 403) setFatal(err.message)
    else setError(err.message)
  }

  async function revisar(e) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      setRevision(await api('/api/familia/activacion/revisar', { metodo: 'POST', datos: { token, ...docs } }))
    } catch (err) { fallo(err) } finally { setEnviando(false) }
  }

  async function completar(e) {
    e.preventDefault()
    setError(null)
    if (!revision.pide_pin_actual && pin.nuevo !== pin.repetir) { setError('Los PIN no coinciden'); return }
    setEnviando(true)
    try {
      const r = await api('/api/familia/activacion/completar', { metodo: 'POST', datos: {
        token, ...docs, acepto,
        ...(revision.pide_pin_actual ? { pin_actual: pin.actual } : { pin: pin.nuevo }) } })
      guardar(r.token)
      navegar('/familia', { replace: true })
    } catch (err) { fallo(err) } finally { setEnviando(false) }
  }

  if (!token || fatal) {
    return (
      <main className="centro">
        <div className="tarjeta">
          <Cabecera colegio={colegio} />
          <p>{fatal || 'Este enlace está incompleto. Ábrelo de nuevo desde el mensaje de WhatsApp.'}</p>
          <Link to="/familia" className="enlace">Ir al ingreso</Link>
        </div>
      </main>
    )
  }

  if (!revision) {
    return (
      <main className="centro">
        <form className="tarjeta" onSubmit={revisar}>
          <Cabecera colegio={colegio} />
          <h2>Activa tu cuenta</h2>
          <p className="tenue">Para confirmar que eres tú, escribe los documentos registrados en el colegio.</p>
          <label>DNI de tu hijo o hija
            <input value={docs.documento_alumno} inputMode="numeric" required
                   onChange={(e) => setDocs({ ...docs, documento_alumno: e.target.value })} />
          </label>
          <label>Tu DNI
            <input value={docs.documento_apoderado} inputMode="numeric" required
                   onChange={(e) => setDocs({ ...docs, documento_apoderado: e.target.value })} />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="boton" disabled={enviando}>Continuar</button>
        </form>
      </main>
    )
  }

  return (
    <main className="centro">
      <form className="tarjeta ancho" onSubmit={completar}>
        <Cabecera colegio={colegio} />
        <h2>Hola, {revision.nombres}</h2>
        <div className="consentimiento">
          <p>{revision.consentimiento.texto}</p>
          <label className="casilla">
            <input type="checkbox" checked={acepto} onChange={(e) => setAcepto(e.target.checked)} />
            Acepto el tratamiento de mis datos y los de mi hijo o hija
          </label>
        </div>
        {revision.pide_pin_actual ? (
          <label>Ya tienes cuenta por otro colegio: escribe tu PIN de siempre
            <input type="password" inputMode="numeric" maxLength={6} required value={pin.actual}
                   onChange={(e) => setPin({ ...pin, actual: e.target.value })} />
          </label>
        ) : (
          <>
            <label>Crea tu PIN (6 números, que no sean seguidos ni repetidos)
              <input type="password" inputMode="numeric" maxLength={6} required value={pin.nuevo}
                     autoComplete="new-password" onChange={(e) => setPin({ ...pin, nuevo: e.target.value })} />
            </label>
            <label>Repite el PIN
              <input type="password" inputMode="numeric" maxLength={6} required value={pin.repetir}
                     autoComplete="new-password" onChange={(e) => setPin({ ...pin, repetir: e.target.value })} />
            </label>
          </>
        )}
        {error && <p className="error">{error}</p>}
        <button className="boton" disabled={enviando || !acepto}>Activar mi cuenta</button>
      </form>
    </main>
  )
}

// --- Inicio: tarjetas en vivo, avisos, ajustes -------------------------------------------

function Inicio({ colegio }) {
  const navegar = useNavigate()
  const [yo, setYo] = useState(null)
  const [datos, setDatos] = useState(null)
  const [avisos, setAvisos] = useState([])
  const [error, setError] = useState(null)
  const [vuelta, setVuelta] = useState(0)  // cambia para recargar el cuaderno

  const salir = useCallback(() => {
    guardar(null)
    navegar('/familia', { replace: true })
  }, [navegar])

  const cargar = useCallback(() => {
    api('/api/familia/hijos').then(setDatos).catch((e) => setError(e.message))
    api('/api/familia/avisos').then(setAvisos).catch(() => {})
    setVuelta((v) => v + 1)
  }, [])

  useEffect(() => {
    api('/api/familia/yo').then(setYo).catch((e) => setError(e.message))
    cargar()
    // En vivo: cada 30 s mientras está a la vista, y al instante cuando llega un aviso.
    const cada = setInterval(() => { if (document.visibilityState === 'visible') cargar() }, 30000)
    const alVolver = () => { if (document.visibilityState === 'visible') cargar() }
    const alAviso = (e) => { if (e.data?.tipo === 'aviso') cargar() }
    document.addEventListener('visibilitychange', alVolver)
    navigator.serviceWorker?.addEventListener('message', alAviso)
    window.addEventListener('sesion-familia-cerrada', salir)
    return () => {
      clearInterval(cada)
      document.removeEventListener('visibilitychange', alVolver)
      navigator.serviceWorker?.removeEventListener('message', alAviso)
      window.removeEventListener('sesion-familia-cerrada', salir)
    }
  }, [cargar, salir])

  if (!tokenFamilia()) return <Navigate to="/familia" replace />

  return (
    <div className="familia">
      <Cabecera colegio={colegio}>
        <div className="usuario">
          {yo && <span>{yo.nombres}</span>}
          <button className="enlace" onClick={salir}>Salir</button>
        </div>
      </Cabecera>
      <main className="familia-contenido">
        {error && <p className="error">{error}</p>}
        {datos?.pendientes_aprobacion.length > 0 && (
          <p className="aviso">
            Tu cuenta en {datos.pendientes_aprobacion.join(', ')} espera la aprobación del colegio.
            Te avisaremos cuando esté lista.
          </p>
        )}
        {datos && datos.hijos.length === 0 && datos.pendientes_aprobacion.length === 0 && (
          <p className="tenue">No hay alumnos vinculados a tu cuenta. Comunícate con el colegio.</p>
        )}
        <div className="hijos">
          {datos?.hijos.map((h) => <TarjetaHijo key={`${h.colegio}-${h.alumno_id}`} hijo={h}
                                                varios={new Set(datos.hijos.map((x) => x.colegio)).size > 1} />)}
        </div>
        {yo && <Notificaciones yo={yo} />}
        {yo?.estado === 'activo' && <ListaCuaderno recargar={vuelta} />}
        <h2>Avisos</h2>
        {avisos.length === 0 ? <p className="tenue">Aún no hay avisos.</p> : (
          <ul className="lista-avisos">
            {avisos.map((a) => (
              <li key={a.id}>
                <span>{a.cuerpo}</span>
                <time className="tenue">{fechaHora(a.creado_en)}</time>
              </li>
            ))}
          </ul>
        )}
        {yo && <Ajustes yo={yo} alCambiar={() => api('/api/familia/yo').then(setYo)} />}
      </main>
    </div>
  )
}

function TarjetaHijo({ hijo, varios }) {
  let estado, clase
  if (!hijo.lectivo && !hijo.estado) [estado, clase] = ['Hoy no hay clases', 'neutro']
  else if (hijo.salida) [estado, clase] = [`Salió a las ${hijo.salida}`, 'salida']
  else if (hijo.estado === 'presente') [estado, clase] = [`Ingresó a las ${hijo.entrada}`, 'presente']
  else if (hijo.estado === 'tarde') {
    [estado, clase] = [`Llegó tarde a las ${hijo.entrada} (${hijo.minutos_tarde} min)`, 'tarde']
  } else if (hijo.estado === 'falta') [estado, clase] = ['No asistió hoy', 'falta']
  else if (hijo.estado === 'justificada') [estado, clase] = ['No asistió hoy (falta justificada)', 'neutro']
  else [estado, clase] = ['Aún no registra su ingreso', 'neutro']
  return (
    <article className={`hijo ${clase}`}>
      <h3>{hijo.nombres} {hijo.apellidos}</h3>
      <p className="tenue">{[hijo.seccion, varios && hijo.colegio].filter(Boolean).join(' · ')}</p>
      <p className="estado-hijo">{estado}</p>
      {hijo.salida && hijo.entrada && <p className="tenue">Ingresó a las {hijo.entrada}</p>}
    </article>
  )
}

function Notificaciones({ yo }) {
  const soporta = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  const [permiso, setPermiso] = useState(soporta ? Notification.permission : 'no')
  const [activas, setActivas] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!soporta) return
    navigator.serviceWorker.ready.then((r) => r.pushManager.getSubscription()).then((s) => {
      setActivas(Boolean(s))
      // Renueva en el servidor: pudo ser otra persona la que entró antes en este celular.
      if (s && Notification.permission === 'granted') {
        api('/api/familia/push/suscripcion', { metodo: 'POST', datos: s.toJSON() }).catch(() => {})
      }
    })
  }, [soporta])

  async function activar() {
    setError(null)
    try {
      const p = await Notification.requestPermission()
      setPermiso(p)
      if (p !== 'granted') return
      const registro = await navigator.serviceWorker.ready
      const s = await registro.pushManager.subscribe({ userVisibleOnly: true,
        applicationServerKey: llaveVapid(yo.push_clave) })
      await api('/api/familia/push/suscripcion', { metodo: 'POST', datos: s.toJSON() })
      setActivas(true)
    } catch (err) { setError(err.message || 'No se pudieron activar los avisos') }
  }

  if (activas) return null
  let texto
  if (!yo.push_clave) texto = 'Los avisos al celular aún no están disponibles en este colegio.'
  else if (!soporta) {
    texto = 'Para recibir avisos, agrega esta página a tu pantalla de inicio (menú del navegador › ' +
      '“Agregar a pantalla de inicio”) y ábrela desde ahí.'
  } else if (permiso === 'denied') {
    texto = 'Bloqueaste las notificaciones. Actívalas en los ajustes del navegador para recibir los avisos.'
  }
  return (
    <section className="aviso">
      <p><b>Recibe un aviso cuando tu hijo ingrese, llegue tarde, falte o salga, y cuando el colegio te escriba.</b></p>
      {texto ? <p className="tenue">{texto}</p>
        : <button className="boton" onClick={activar}>Activar avisos</button>}
      {error && <p className="error">{error}</p>}
    </section>
  )
}

function Ajustes({ yo, alCambiar }) {
  const [pin, setPin] = useState({ pin_actual: '', pin_nuevo: '' })
  const [mensaje, setMensaje] = useState(null)
  const [error, setError] = useState(null)

  async function registrarHuella() {
    setError(null)
    setMensaje(null)
    try {
      const { opciones, reto } = await api('/api/familia/passkey/opciones-registro', { metodo: 'POST' })
      const credencial = await crearPasskey(opciones)
      await api('/api/familia/passkey/registro', { metodo: 'POST', datos: { credencial, reto } })
      setMensaje('Listo: la próxima vez entra con tu huella o rostro.')
      alCambiar()
    } catch (err) {
      if (err.name !== 'NotAllowedError') setError(err.message)
    }
  }

  async function cambiarPin(e) {
    e.preventDefault()
    setError(null)
    setMensaje(null)
    try {
      const r = await api('/api/familia/pin', { metodo: 'PUT', datos: pin })
      guardar(r.token)
      setPin({ pin_actual: '', pin_nuevo: '' })
      setMensaje('PIN cambiado. Se cerró la sesión en tus otros celulares.')
    } catch (err) { setError(err.message) }
  }

  return (
    <details className="ajustes">
      <summary>Mi cuenta</summary>
      {hayPasskeys() && !yo.tiene_passkey && (
        <button className="boton secundario" onClick={registrarHuella}>Entrar con huella o rostro en este celular</button>
      )}
      <form className="fila-form" onSubmit={cambiarPin}>
        <input type="password" inputMode="numeric" maxLength={6} placeholder="PIN actual" required
               value={pin.pin_actual} onChange={(e) => setPin({ ...pin, pin_actual: e.target.value })} />
        <input type="password" inputMode="numeric" maxLength={6} placeholder="PIN nuevo" required
               autoComplete="new-password" value={pin.pin_nuevo}
               onChange={(e) => setPin({ ...pin, pin_nuevo: e.target.value })} />
        <button className="boton">Cambiar PIN</button>
      </form>
      {mensaje && <p>{mensaje}</p>}
      {error && <p className="error">{error}</p>}
    </details>
  )
}

function fechaHora(iso) {
  return new Date(iso).toLocaleString('es-PE', { timeZone: 'America/Lima', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit' })
}
