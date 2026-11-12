import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, CLAVE_TOKEN_FAMILIA, guardarToken } from '../api.js'
import Cabecera from '../espacios/Cabecera.jsx'
import '../espacios/reunion.css'
import { Cargando, Mensaje } from '../espacios/comun/index.js'

// Modo reunión, lado del padre: escanea el QR del aula, escribe el DNI de su hijo, llena su
// ficha y espera a que el tutor la apruebe; si el tutor activa su cuenta, crea su PIN aquí.
// En la tablet del aula (modo quiosco) no se guarda nada y vuelve a empezar para el siguiente.

const CLAVE_QR = 'tikray.reunion.qr'
const CLAVE_FICHA = 'tikray.reunion.ficha'
const TIPOS = [['DNI', 'DNI'], ['CE', 'Carné de extranjería'], ['PAS', 'Pasaporte'], ['OTRO', 'Otro']]
const VACIA = { tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '', celular: '', correo: '',
  parentesco: 'Madre' }

function leer(almacen, clave) { try { return almacen.getItem(clave) } catch { return null } }
function escribir(almacen, clave, valor) {
  try { valor == null ? almacen.removeItem(clave) : almacen.setItem(clave, valor) } catch { /* modo privado */ }
}

export default function Reunion({ colegio }) {
  const quiosco = new URLSearchParams(window.location.search).has('quiosco')
  // El código del QR va después del #; se guarda en la pestaña para que una recarga no lo pierda.
  const [token] = useState(() => {
    const delHash = window.location.hash.slice(1)
    if (delHash) escribir(sessionStorage, CLAVE_QR, delHash)
    return delHash || leer(sessionStorage, CLAVE_QR)
  })
  const [codigo, setCodigo] = useState(() => (quiosco ? null : leer(localStorage, CLAVE_FICHA)))
  const [info, setInfo] = useState(null)
  const [fatal, setFatal] = useState(null)

  useEffect(() => {
    if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search)
  }, [])

  useEffect(() => {
    if (!token || codigo) return
    api('/api/familia/reunion/abrir', { metodo: 'POST', datos: { token } })
      .then(setInfo).catch((e) => setFatal(e.message))
  }, [token, codigo])

  const terminar = useCallback((nuevo) => {
    escribir(localStorage, CLAVE_FICHA, nuevo)
    setCodigo(nuevo)
  }, [])

  if (codigo) return <Espera colegio={colegio} codigo={codigo} corregir={() => terminar(null)} />
  if (!token || fatal) {
    return (
      <main className="centro">
        <div className="tarjeta">
          <Cabecera colegio={colegio} />
          <p>{fatal || 'Escanea el código QR que muestra el tutor en el aula.'}</p>
          <Link to="/familia" className="enlace">Ir al ingreso</Link>
        </div>
      </main>
    )
  }
  if (!info) return <main className="centro"><Cargando /></main>
  return <Llenar colegio={colegio} token={token} info={info} quiosco={quiosco} terminar={terminar} />
}

function Llenar({ colegio, token, info, quiosco, terminar }) {
  const [documento, setDocumento] = useState('')
  const [alumno, setAlumno] = useState(null)
  const [yo, setYo] = useState({ ...VACIA })
  const [conOtro, setConOtro] = useState(false)
  const [otro, setOtro] = useState({ ...VACIA, parentesco: 'Padre' })
  const [acepto, setAcepto] = useState(false)
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [gracias, setGracias] = useState(null)

  function reiniciar() {
    setDocumento(''); setAlumno(null); setYo({ ...VACIA }); setConOtro(false)
    setOtro({ ...VACIA, parentesco: 'Padre' }); setAcepto(false); setError(null); setGracias(null)
  }

  // En la tablet, la pantalla de "gracias" vuelve sola al inicio para el siguiente padre.
  useEffect(() => {
    if (!gracias) return
    const t = setTimeout(reiniciar, 8000)
    return () => clearTimeout(t)
  }, [gracias])

  async function buscar(e) {
    e.preventDefault()
    setEnviando(true); setError(null)
    try {
      const r = await api('/api/familia/reunion/alumno', { metodo: 'POST', datos: { token, documento_alumno: documento } })
      setAlumno(r.alumno)
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  async function enviar(e) {
    e.preventDefault()
    setEnviando(true); setError(null)
    const limpio = (p) => ({ ...p, correo: p.correo || null, celular: p.celular || null })
    try {
      const r = await api('/api/familia/reunion/ficha', { metodo: 'POST', datos: {
        token, documento_alumno: documento, apoderado: limpio(yo), otro: conOtro ? limpio(otro) : null, acepto, quiosco } })
      if (quiosco) setGracias(r.alumno)
      else terminar(r.codigo)
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  const titulo = <p className="tenue">{info.titulo} · {info.seccion}</p>

  if (gracias) {
    return (
      <main className="centro">
        <div className="tarjeta">
          <Cabecera colegio={colegio} />
          <h2>¡Gracias!</h2>
          <p>La ficha de {gracias} llegó al tutor. Acércate para que la apruebe.</p>
          <p className="tenue">Entrega la tablet al siguiente padre o madre.</p>
          <button className="boton" onClick={reiniciar}>Siguiente ficha</button>
        </div>
      </main>
    )
  }

  if (!alumno) {
    return (
      <main className="centro">
        <form className="tarjeta" onSubmit={buscar}>
          <Cabecera colegio={colegio} />
          <h2>Ficha del apoderado</h2>
          {titulo}
          <label>DNI de tu hijo o hija (de esta aula)
            <input value={documento} inputMode="numeric" required autoComplete="off"
                   onChange={(e) => setDocumento(e.target.value)} />
          </label>
          {error && <Mensaje tipo="error">{error}</Mensaje>}
          <button className="boton" disabled={enviando}>Continuar</button>
          {quiosco && <p className="tenue">Tablet del aula: no se guarda nada en este equipo.</p>}
        </form>
      </main>
    )
  }

  return (
    <main className="centro">
      <form className="tarjeta ancho" onSubmit={enviar} autoComplete={quiosco ? 'off' : 'on'}>
        <Cabecera colegio={colegio} />
        <h2>Ficha del apoderado de {alumno}</h2>
        {titulo}
        <fieldset className="ficha-persona">
          <legend>Tus datos</legend>
          <CamposPersona p={yo} cambiar={setYo} parentescos={info.parentescos} quiosco={quiosco} obligatorioCelular />
        </fieldset>
        <label className="casilla">
          <input type="checkbox" checked={conOtro} onChange={(e) => setConOtro(e.target.checked)} />
          Agregar al otro apoderado (padre, madre u otra persona a cargo)
        </label>
        {conOtro && (
          <fieldset className="ficha-persona">
            <legend>Otro apoderado</legend>
            <CamposPersona p={otro} cambiar={setOtro} parentescos={info.parentescos} quiosco={quiosco} />
          </fieldset>
        )}
        <div className="consentimiento">
          <p>{info.consentimiento.texto}</p>
          <label className="casilla">
            <input type="checkbox" checked={acepto} onChange={(e) => setAcepto(e.target.checked)} />
            Acepto el tratamiento de mis datos y los de mi hijo o hija
          </label>
        </div>
        <p className="tenue">El tutor revisará tu ficha en la reunión. Nada cambia hasta que la apruebe.</p>
        {error && <Mensaje tipo="error">{error}</Mensaje>}
        <div className="acciones">
          <button className="boton" disabled={enviando || !acepto}>Enviar ficha</button>
          <button type="button" className="enlace" onClick={reiniciar}>Empezar de nuevo</button>
        </div>
      </form>
    </main>
  )
}

function CamposPersona({ p, cambiar, parentescos, quiosco, obligatorioCelular = false }) {
  const campo = (clave) => (e) => cambiar({ ...p, [clave]: e.target.value })
  const auto = (valor) => (quiosco ? 'off' : valor)
  return (
    <div className="ficha-campos">
      <label>Tipo de documento
        <select value={p.tipo_documento} onChange={campo('tipo_documento')}>
          {TIPOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
      </label>
      <label>Número de documento
        <input value={p.numero_documento} required inputMode={p.tipo_documento === 'DNI' ? 'numeric' : 'text'}
               autoComplete="off" onChange={campo('numero_documento')} />
      </label>
      <label>Nombres
        <input value={p.nombres} required autoComplete={auto('given-name')} onChange={campo('nombres')} />
      </label>
      <label>Apellidos
        <input value={p.apellidos} required autoComplete={auto('family-name')} onChange={campo('apellidos')} />
      </label>
      <label>Celular
        <input value={p.celular} required={obligatorioCelular} inputMode="tel" autoComplete={auto('tel-national')}
               placeholder="9 dígitos" onChange={campo('celular')} />
      </label>
      <label>Correo (opcional)
        <input value={p.correo} type="email" autoComplete={auto('email')} onChange={campo('correo')} />
      </label>
      <label>Parentesco
        <select value={p.parentesco} onChange={campo('parentesco')}>
          {parentescos.map((x) => <option key={x}>{x}</option>)}
        </select>
      </label>
    </div>
  )
}

function Espera({ colegio, codigo, corregir }) {
  const navegar = useNavigate()
  const [estado, setEstado] = useState(null)
  const [error, setError] = useState(null)
  const [pin, setPin] = useState({ actual: '', nuevo: '', repetir: '' })
  const [enviando, setEnviando] = useState(false)
  const activando = useRef(false)

  useEffect(() => {
    let vivo = true
    const mirar = () => {
      if (activando.current) return
      api('/api/familia/reunion/estado', { metodo: 'POST', datos: { codigo } })
        .then((r) => vivo && setEstado(r))
        .catch((e) => {
          if (!vivo) return
          if (e.estado === 404 || e.estado === 410) { corregir(); return }
          setError(e.message)
        })
    }
    mirar()
    const t = setInterval(mirar, 4000)
    return () => { vivo = false; clearInterval(t) }
  }, [codigo, corregir])

  async function activar(e) {
    e.preventDefault()
    setError(null)
    if (!estado.pide_pin_actual && pin.nuevo !== pin.repetir) { setError('Los PIN no coinciden'); return }
    setEnviando(true)
    activando.current = true
    try {
      const r = await api('/api/familia/reunion/activar', { metodo: 'POST', datos: {
        codigo, ...(estado.pide_pin_actual ? { pin_actual: pin.actual } : { pin: pin.nuevo }) } })
      guardarToken(r.token, CLAVE_TOKEN_FAMILIA)
      escribir(localStorage, CLAVE_FICHA, null)
      navegar('/familia', { replace: true })
    } catch (err) { setError(err.message); activando.current = false } finally { setEnviando(false) }
  }

  function listo() {
    escribir(localStorage, CLAVE_FICHA, null)
    navegar('/familia', { replace: true })
  }

  let cuerpo = <Cargando />
  if (estado?.estado === 'pendiente') {
    cuerpo = (
      <>
        <h2>Tu ficha llegó al tutor</h2>
        <p>Acércate al tutor para que la revise contigo. Esta pantalla cambia sola cuando la apruebe.</p>
        <p className="espera-punto" aria-hidden="true">●</p>
        <button className="enlace" onClick={corregir}>Corregir mi ficha</button>
      </>
    )
  } else if (estado?.estado === 'rechazada') {
    cuerpo = (
      <>
        <h2>El tutor no aprobó tu ficha</h2>
        {estado.motivo && <p>Motivo: {estado.motivo}</p>}
        <button className="boton" onClick={corregir}>Llenar de nuevo</button>
      </>
    )
  } else if (estado?.estado === 'aprobada' && estado.puede_activar) {
    cuerpo = (
      <form onSubmit={activar}>
        <h2>¡Ficha aprobada, {estado.nombres}!</h2>
        <p>Ahora activa tu cuenta para recibir los avisos de asistencia y el cuaderno de control.</p>
        {estado.pide_pin_actual ? (
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
        <button className="boton" disabled={enviando}>Activar mi cuenta</button>
      </form>
    )
  } else if (estado?.estado === 'aprobada') {
    cuerpo = (
      <>
        <h2>¡Ficha aprobada!</h2>
        <p>{estado.activa ? 'Tu cuenta ya está activa: entra con tu DNI y tu PIN.'
          : 'Tus datos quedaron registrados. El colegio te enviará tu enlace personal para activar tu cuenta.'}</p>
        <button className="boton" onClick={listo}>{estado.activa ? 'Entrar' : 'Terminar'}</button>
      </>
    )
  }

  return (
    <main className="centro">
      <div className="tarjeta">
        <Cabecera colegio={colegio} />
        {cuerpo}
        {error && <Mensaje tipo="error">{error}</Mensaje>}
      </div>
    </main>
  )
}
