import { useEffect, useState } from 'react'
import { ArrowLeft, Fingerprint } from 'lucide-react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, CLAVE_TOKEN_FAMILIA, guardarToken } from '../api.js'
import AppFamilia, { AsistenciaHijo, CuadernoFamilia, Inicio, Perfil } from '../familia/App.jsx'
import { DetalleCuaderno, PedidoCuaderno } from '../familia/Cuaderno.jsx'
import PagosFamilia from '../familia/Pagos.jsx'
import RecojoFamilia from '../familia/Recojo.jsx'
import CalendarioFamilia from '../familia/Calendario.jsx'
import AutorizacionesFamilia from '../familia/Autorizaciones.jsx'
import Reunion from '../familia/Reunion.jsx'
import { hayPasskeys, usarPasskey } from '../familia/webauthn.js'
import Acceso from './Acceso.jsx'
import Cabecera from './Cabecera.jsx'
import './familia.css'

const guardar = (t) => guardarToken(t, CLAVE_TOKEN_FAMILIA)

export default function Familia({ colegio }) {
  useLocation()  // al entrar o salir cambia la ruta: volver a leer el token
  return (
    <Routes>
      <Route path="activar" element={<Activar colegio={colegio} />} />
      <Route path="reunion" element={<Reunion colegio={colegio} />} />
      <Route element={<AppFamilia colegio={colegio} ingreso={<Ingreso colegio={colegio} />} />}>
        <Route index element={<Inicio />} />
        <Route path="asistencia" element={<AsistenciaHijo />} />
        <Route path="cuaderno" element={<CuadernoFamilia />} />
        <Route path="pagos" element={<PagosFamilia />} />
        <Route path="recojo" element={<RecojoFamilia />} />
        <Route path="calendario" element={<CalendarioFamilia />} />
        <Route path="autorizaciones" element={<AutorizacionesFamilia />} />
        <Route path="perfil" element={<Perfil />} />
        <Route path="cuaderno/nuevo/:tipo" element={<PedidoCuaderno />} />
        <Route path="cuaderno/:id" element={<DetalleCuaderno />} />
      </Route>
      <Route path="*" element={<Navigate to="/familia" replace />} />
    </Routes>
  )
}

// --- Ingreso: huella, o documento + PIN ---------------------------------------------------

function Ingreso({ colegio }) {
  const navegar = useNavigate()
  const [documento, setDocumento] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [olvido, setOlvido] = useState(false)

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
    <Acceso colegio={colegio}>
      <Link to="/" className="enlace acceso-volver"><ArrowLeft size={18} aria-hidden="true" /> Volver</Link>
      <h1>Padres y apoderados</h1>
      <p className="acceso-subtitulo">Ingrese con la huella de su celular o con su PIN</p>
      {hayPasskeys() && <>
        <button type="button" className="boton grande" disabled={enviando} onClick={() => entrar(conPasskey())}>
          <Fingerprint size={22} aria-hidden="true" /> Ingresar con huella
        </button>
        <div className="acceso-separador">o con su documento</div>
      </>}
      <form className="acceso-form" onSubmit={(e) => {
        e.preventDefault()
        entrar(api('/api/familia/ingreso', { metodo: 'POST', datos: { documento, pin } }))
      }}>
        <label>DNI o carné de extranjería
          <input value={documento} onChange={(e) => setDocumento(e.target.value)} autoComplete="username" required />
        </label>
        <label>PIN (6 números)
          <input type="password" value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric"
                 maxLength={6} autoComplete="current-password" required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className={hayPasskeys() ? 'boton grande secundario' : 'boton grande'} disabled={enviando}>Ingresar</button>
      </form>
      <button type="button" className="enlace" aria-expanded={olvido} onClick={() => setOlvido(!olvido)}>Olvidé mi PIN</button>
      {olvido && (
        <p className="acceso-nota">
          Pida un PIN nuevo en secretaría. El colegio le enviará por WhatsApp un enlace personal para crearlo.
        </p>
      )}
      <p className="acceso-nota">
        <b>¿Primera vez?</b> Abra el enlace que el colegio le envió por WhatsApp. Si no lo tiene, pídalo en secretaría.
      </p>
    </Acceso>
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
