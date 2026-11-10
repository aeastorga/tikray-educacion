// App de la familia (celular primero): inicio con la tarjeta en vivo, asistencia del mes, cuaderno y perfil.
import {
  Bell, CalendarCheck, CalendarDays, ChevronLeft, ChevronRight, DoorOpen, Fingerprint, House, LogIn, LogOut, NotebookPen,
  PenLine, ShieldCheck, UserRound, Wallet,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, NavLink, Outlet, useLocation, useNavigate, useOutletContext } from 'react-router-dom'
import { api, CLAVE_TOKEN_FAMILIA, guardarToken, leerToken } from '../api.js'
import { Apariencia } from '../Apariencia.jsx'
import { Logo } from '../espacios/Acceso.jsx'
import { hora12, LIMA, saludo } from '../tema.js'
import { ListaCuaderno } from './Cuaderno.jsx'
import { crearPasskey, hayPasskeys, llaveVapid } from './webauthn.js'
import './app.css'

const tokenFamilia = () => leerToken(CLAVE_TOKEN_FAMILIA)
const guardar = (t) => guardarToken(t, CLAVE_TOKEN_FAMILIA)
const BOTON_FIRMA = { comunicado: 'Firmar lectura', incidencia: 'Enterado', citacion: 'Confirmo que asistiré' }

export default function AppFamilia({ colegio, ingreso }) {
  const navegar = useNavigate()
  const { pathname } = useLocation()
  const [yo, setYo] = useState(null)
  const [datos, setDatos] = useState(null)
  const [avisos, setAvisos] = useState([])
  const [cuaderno, setCuaderno] = useState(null)
  const [error, setError] = useState(null)
  const [vuelta, setVuelta] = useState(0)  // cambia para recargar el cuaderno
  const [elegido, setElegido] = useState(null)
  const conSesion = Boolean(tokenFamilia())

  const salir = useCallback(() => {
    guardar(null)
    navegar('/familia', { replace: true })
  }, [navegar])

  const cargar = useCallback(() => {
    api('/api/familia/hijos').then(setDatos).catch((e) => setError(e.message))
    api('/api/familia/avisos').then(setAvisos).catch(() => {})
    api('/api/familia/cuaderno').then(setCuaderno).catch(() => setCuaderno(null))
    setVuelta((v) => v + 1)
  }, [])

  useEffect(() => {
    if (!conSesion) return undefined
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
  }, [cargar, salir, conSesion])

  if (!conSesion) return pathname.replace(/\/$/, '') === '/familia' ? ingreso : <Navigate to="/familia" replace />

  const hijos = datos?.hijos || []
  const hijo = hijos.find((h) => clave(h) === elegido) || hijos[0] || null
  const porFirmar = (cuaderno?.entradas || []).filter((e) => e.pide_firma && !e.firmado_en)
  const contexto = { colegio, yo, setYo, datos, hijos, hijo, elegir: setElegido, avisos, cuaderno, porFirmar,
    vuelta, cargar, salir, error }

  return (
    <div className="app-familia">
      <header className="app-cabecera">
        <Logo colegio={colegio} className="app-logo" />
        <span className="app-colegio">{colegio.nombre}</span>
      </header>
      <div className="app-contenido">
        <Outlet context={contexto} />
      </div>
      <nav className="barra-inferior" aria-label="Secciones">
        <NavLink to="/familia" end><House aria-hidden="true" /><span>Inicio</span></NavLink>
        {yo?.modulos?.asistencia !== false && (
          <NavLink to="/familia/asistencia"><CalendarCheck aria-hidden="true" /><span>Asistencia</span></NavLink>
        )}
        {yo?.modulos?.cuaderno !== false && (
          <NavLink to="/familia/cuaderno">
            <NotebookPen aria-hidden="true" /><span>Cuaderno</span>
            {porFirmar.length > 0 && <b className="contador-menu" aria-label={`${porFirmar.length} por firmar`}>{porFirmar.length}</b>}
          </NavLink>
        )}
        {yo?.modulos?.calendario && (
          <NavLink to="/familia/calendario"><CalendarDays aria-hidden="true" /><span>Calendario</span></NavLink>
        )}
        {yo?.modulos?.pensiones && (
          <NavLink to="/familia/pagos"><Wallet aria-hidden="true" /><span>Pagos</span></NavLink>
        )}
        <NavLink to="/familia/perfil"><UserRound aria-hidden="true" /><span>Perfil</span></NavLink>
      </nav>
    </div>
  )
}

const clave = (h) => `${h.colegio}-${h.alumno_id}`

function fechaLarga() {
  const t = new Date().toLocaleDateString('es-PE', { timeZone: LIMA, weekday: 'long', day: 'numeric', month: 'long' })
  return t.charAt(0).toUpperCase() + t.slice(1)
}

// Selector de hijos en píldoras (también los de otros colegios).
function Hijos({ hijos, hijo, elegir }) {
  if (hijos.length < 2) return null
  const variosColegios = new Set(hijos.map((h) => h.colegio)).size > 1
  return (
    <div className="pildoras" role="group" aria-label="Hijos">
      {hijos.map((h) => (
        <button key={clave(h)} type="button" className="pildora" aria-pressed={clave(h) === clave(hijo)}
                onClick={() => elegir(clave(h))}>
          {h.nombres.split(' ')[0]}
          {variosColegios && <small>{h.colegio}</small>}
        </button>
      ))}
    </div>
  )
}

// --- Inicio ------------------------------------------------------------------------------------

export function Inicio() {
  const { yo, datos, hijos, hijo, elegir, avisos, porFirmar, cargar, error } = useOutletContext()
  return (
    <>
      <div className="saludo">
        <p className="tenue">{fechaLarga()}</p>
        <h1>{saludo()}{yo ? `, ${yo.nombres.split(' ')[0]}` : ''}</h1>
      </div>
      {error && <p className="error">{error}</p>}
      {datos?.pendientes_aprobacion.length > 0 && (
        <p className="aviso">
          Su cuenta en {datos.pendientes_aprobacion.join(', ')} espera la aprobación del colegio.
          Le avisaremos cuando esté lista.
        </p>
      )}
      {datos && hijos.length === 0 && datos.pendientes_aprobacion.length === 0 && (
        <p className="tenue">No hay alumnos vinculados a su cuenta. Comuníquese con el colegio.</p>
      )}
      <Hijos hijos={hijos} hijo={hijo} elegir={elegir} />
      {hijo && hijo.asistencia !== false && <TarjetaEnVivo hijo={hijo} varios={new Set(hijos.map((h) => h.colegio)).size > 1} />}
      {yo && <Notificaciones yo={yo} />}
      {porFirmar.length > 0 && <PorFirmar entrada={porFirmar[0]} mas={porFirmar.length - 1} alFirmar={cargar} />}
      {hijo && hijo.asistencia !== false && <DelDia hijo={hijo} />}
      {yo?.modulos?.recojo && yo.estado === 'activo' && hijos.length > 0 && <TarjetaRecojo />}
      <section className="tarjeta-app">
        <h2>Avisos recientes</h2>
        {avisos.length === 0 ? <p className="tenue">Aún no hay avisos.</p> : (
          <ul className="lista-avisos">
            {avisos.slice(0, 5).map((a) => (
              <li key={a.id}>
                <span>{a.cuerpo}</span>
                <time className="tenue">{fechaHora(a.creado_en)}</time>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}

function estadoDe(hijo) {
  const nombre = hijo.nombres.split(' ')[0]
  if (!hijo.lectivo && !hijo.estado) return { titulo: 'Hoy no hay clases', chip: 'Sin clases', clase: 'neutro' }
  if (hijo.salida) return { titulo: `${nombre} salió del colegio a las ${hora12(hijo.salida)}`, ...chipIngreso(hijo) }
  if (hijo.estado === 'presente') return { titulo: `${nombre} ingresó a las ${hora12(hijo.entrada)}`, chip: 'A tiempo', clase: 'a-tiempo' }
  if (hijo.estado === 'tarde') return { titulo: `${nombre} ingresó a las ${hora12(hijo.entrada)}`, ...chipIngreso(hijo) }
  if (hijo.estado === 'falta') return { titulo: `${nombre} no asistió hoy`, chip: 'Falta', clase: 'falta' }
  if (hijo.estado === 'justificada') return { titulo: `${nombre} no asistió hoy`, chip: 'Falta justificada', clase: 'justificada' }
  return { titulo: `${nombre} aún no registra su ingreso`, chip: 'Esperando ingreso', clase: 'neutro' }
}

function chipIngreso(hijo) {
  return hijo.estado === 'tarde'
    ? { chip: `Tarde · ${hijo.minutos_tarde} min`, clase: 'tarde' }
    : { chip: 'A tiempo', clase: 'a-tiempo' }
}

// Recojo seguro: "con Rosa Mamani (madre)", si la portería lo registró.
function conQuien(r) {
  if (!r) return ''
  return ` · con ${r.nombre}${r.parentesco ? ` (${r.parentesco.toLowerCase()})` : ''}`
}

function TarjetaEnVivo({ hijo, varios }) {
  const e = estadoDe(hijo)
  const salida = hijo.salida ? hora12(hijo.salida) : hijo.hora_salida ? `${hora12(hijo.hora_salida)} (programada)` : '—'
  return (
    <article className="en-vivo" aria-live="polite">
      <div className="en-vivo-arriba">
        <span className="en-vivo-punto"><i aria-hidden="true" /> En vivo</span>
        <span className={`chip-estado ${e.clase}`}>{e.chip}</span>
      </div>
      <h2 className="en-vivo-titulo">{e.titulo}</h2>
      <p className="en-vivo-alumno">{hijo.nombres} {hijo.apellidos}{varios ? ` · ${hijo.colegio}` : ''}</p>
      {hijo.salida && hijo.recogido_por && (
        <p className="en-vivo-recojo">
          Lo recogió {hijo.recogido_por.nombre}{hijo.recogido_por.parentesco ? ` (${hijo.recogido_por.parentesco.toLowerCase()})` : ''}
          {hijo.recogido_por.fuera_de_lista && <span className="chip-estado falta">No está en su lista</span>}
        </p>
      )}
      <dl className="en-vivo-datos">
        <div><dt>Puerta</dt><dd>{hijo.puerta || '—'}</dd></div>
        <div><dt>Sección</dt><dd>{hijo.seccion || '—'}</dd></div>
        <div><dt>Salida</dt><dd>{salida}</dd></div>
        <div><dt>Tardanzas del mes</dt><dd>{hijo.tardanzas_mes ?? 0}</dd></div>
      </dl>
    </article>
  )
}

function PorFirmar({ entrada, mas, alFirmar }) {
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState(null)
  const navegar = useNavigate()

  async function firmar() {
    setEnviando(true)
    setError(null)
    try { await api(`/api/familia/cuaderno/${entrada.id}/firmar`, { metodo: 'POST' }); alFirmar() }
    catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  return (
    <section className="tarjeta-app por-firmar">
      <div className="por-firmar-cabeza">
        <span className="por-firmar-icono"><PenLine size={20} aria-hidden="true" /></span>
        <div>
          <h2>Por firmar</h2>
          <p className="tenue">Cuaderno de control{mas > 0 ? ` · y ${mas} más` : ''}</p>
        </div>
      </div>
      <button type="button" className="por-firmar-titulo" onClick={() => navegar(`/familia/cuaderno/${entrada.id}`)}>
        <b>{entrada.titulo}</b>
        <span className="tenue">{entrada.alumnos.join(', ')} · {fechaHora(entrada.creado_en)}</span>
      </button>
      {error && <p className="error">{error}</p>}
      <button type="button" className="boton grande" disabled={enviando} onClick={firmar}>
        {BOTON_FIRMA[entrada.tipo] || 'Firmar lectura'}
      </button>
    </section>
  )
}

// Recojo seguro: acceso a la lista de quién puede recoger a los hijos.
function TarjetaRecojo() {
  const navegar = useNavigate()
  return (
    <section className="tarjeta-app activar-avisos">
      <span className="por-firmar-icono"><ShieldCheck size={20} aria-hidden="true" /></span>
      <div>
        <p><b>Recojo seguro</b></p>
        <p className="tenue">Elija quién puede recoger a sus hijos o autorice a alguien solo por un día.</p>
        <button type="button" className="boton secundario" onClick={() => navegar('/familia/recojo')}>Quién puede recogerlos</button>
      </div>
    </section>
  )
}

function DelDia({ hijo }) {
  if (!hijo.lectivo && !hijo.estado) return null
  const falto = hijo.estado === 'falta' || hijo.estado === 'justificada'
  return (
    <section className="tarjeta-app">
      <h2>Hoy</h2>
      <ol className="linea-dia">
        <li className={hijo.entrada ? 'hecho' : falto ? 'falto' : 'pendiente'}>
          <span className="linea-icono"><LogIn size={18} aria-hidden="true" /></span>
          <span><b>Ingreso</b>
            <small>{hijo.entrada ? `${hora12(hijo.entrada)}${hijo.puerta ? ` · ${hijo.puerta}` : ''}` : falto ? 'No asistió' : 'Pendiente'}</small>
          </span>
          {hijo.entrada && <span className={`chip-estado ${hijo.estado === 'tarde' ? 'tarde' : 'a-tiempo'}`}>{hijo.estado === 'tarde' ? 'Tarde' : 'A tiempo'}</span>}
        </li>
        {!falto && (
          <li className={hijo.salida ? 'hecho' : 'pendiente'}>
            <span className="linea-icono"><DoorOpen size={18} aria-hidden="true" /></span>
            <span><b>Salida</b>
              <small>{hijo.salida ? `${hora12(hijo.salida)}${conQuien(hijo.recogido_por)}` : `Pendiente${hijo.hora_salida ? ` · ${hora12(hijo.hora_salida)}` : ''}`}</small>
            </span>
          </li>
        )}
      </ol>
    </section>
  )
}

// --- Asistencia del mes --------------------------------------------------------------------

const ESTADOS = { presente: 'A tiempo', tarde: 'Tarde', falta: 'Falta', justificada: 'Justificada' }
const CLASE_ESTADO = { presente: 'a-tiempo', tarde: 'tarde', falta: 'falta', justificada: 'justificada' }

function mesLima(desplazar = 0) {
  const [a, m] = new Date().toLocaleDateString('en-CA', { timeZone: LIMA }).split('-').map(Number)
  const d = new Date(Date.UTC(a, m - 1 + desplazar, 15))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}

export function AsistenciaHijo() {
  const { hijos, hijo, elegir } = useOutletContext()
  const [desplazar, setDesplazar] = useState(0)
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const mes = useMemo(() => mesLima(desplazar), [desplazar])
  const id = hijo?.alumno_id

  useEffect(() => {
    if (!id) return
    setD(null)
    api(`/api/familia/hijos/${id}/asistencia?mes=${mes}`).then(setD).catch((e) => setError(e.message))
  }, [id, mes])

  const nombreMes = new Date(`${mes}-15T12:00:00`).toLocaleDateString('es-PE', { month: 'long', year: 'numeric' })
  return (
    <>
      <div className="saludo"><h1>Asistencia</h1></div>
      <Hijos hijos={hijos} hijo={hijo} elegir={elegir} />
      {!hijo && <p className="tenue">No hay alumnos vinculados a su cuenta.</p>}
      {hijo && (
        <section className="tarjeta-app">
          <div className="mes">
            <button type="button" className="boton-icono" aria-label="Mes anterior" onClick={() => setDesplazar(desplazar - 1)}>
              <ChevronLeft aria-hidden="true" />
            </button>
            <h2>{nombreMes.charAt(0).toUpperCase() + nombreMes.slice(1)}</h2>
            <button type="button" className="boton-icono" aria-label="Mes siguiente" disabled={desplazar >= 0}
                    onClick={() => setDesplazar(desplazar + 1)}>
              <ChevronRight aria-hidden="true" />
            </button>
          </div>
          {error && <p className="error">{error}</p>}
          {d && (
            <>
              <div className="resumen-mes">
                {Object.entries(ESTADOS).map(([k, t]) => (
                  <div key={k} className={`caja-estado ${CLASE_ESTADO[k]}`}><b>{d.resumen[k] || 0}</b><span>{t}</span></div>
                ))}
              </div>
              {d.dias.length === 0 ? <p className="tenue">Sin registros en este mes.</p> : (
                <ul className="dias-mes">
                  {d.dias.map((x) => (
                    <li key={x.fecha}>
                      <span className="dia-fecha">
                        {new Date(`${x.fecha}T12:00:00`).toLocaleDateString('es-PE', { weekday: 'short', day: 'numeric' })}
                      </span>
                      <span className="tenue">
                        {x.entrada ? hora12(x.entrada) : '—'}{x.salida ? ` – ${hora12(x.salida)}` : ''}
                        {x.recogido_por && <small className="dia-recojo">Con {x.recogido_por.nombre}</small>}
                      </span>
                      <span className={`chip-estado ${CLASE_ESTADO[x.estado]}`}>
                        {ESTADOS[x.estado]}{x.estado === 'tarde' ? ` · ${x.minutos_tarde} min` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}
    </>
  )
}

// --- Cuaderno y perfil -----------------------------------------------------------------------

export function CuadernoFamilia() {
  const { yo, vuelta } = useOutletContext()
  if (yo?.modulos?.cuaderno === false) return <p className="tenue">El colegio no usa el cuaderno de control en la app.</p>
  if (yo && yo.estado !== 'activo') return <p className="tenue">El cuaderno se abre cuando el colegio aprueba su cuenta.</p>
  return <ListaCuaderno recargar={vuelta} />
}

export function Perfil() {
  const { yo, setYo, avisos, salir } = useOutletContext()
  return (
    <>
      <div className="saludo"><h1>Perfil</h1></div>
      {yo && (
        <section className="tarjeta-app perfil">
          <span className="perfil-iniciales" aria-hidden="true">{yo.nombres[0]}</span>
          <div>
            <b>{yo.nombres}</b>
            <p className="tenue">{yo.tiene_passkey ? 'Ingresa con huella o PIN' : 'Ingresa con PIN'}</p>
          </div>
        </section>
      )}
      {yo && <Notificaciones yo={yo} mostrarActivas />}
      {yo && <Ajustes yo={yo} alCambiar={() => api('/api/familia/yo').then(setYo)} />}
      <section className="tarjeta-app">
        <Apariencia />
      </section>
      <section className="tarjeta-app">
        <h2>Avisos recibidos</h2>
        {avisos.length === 0 ? <p className="tenue">Aún no hay avisos.</p> : (
          <ul className="lista-avisos">
            {avisos.map((a) => (
              <li key={a.id}><span>{a.cuerpo}</span><time className="tenue">{fechaHora(a.creado_en)}</time></li>
            ))}
          </ul>
        )}
      </section>
      <button type="button" className="boton grande secundario" onClick={salir}>
        <LogOut size={20} aria-hidden="true" /> Cerrar sesión
      </button>
    </>
  )
}

function Notificaciones({ yo, mostrarActivas = false }) {
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

  if (activas) {
    return mostrarActivas
      ? <p className="tarjeta-app nota-ok"><Bell size={18} aria-hidden="true" /> Los avisos llegan a este celular.</p>
      : null
  }
  let texto
  if (!yo.push_clave) texto = 'Los avisos al celular aún no están disponibles en este colegio.'
  else if (!soporta) {
    texto = 'Para recibir avisos, agregue esta página a su pantalla de inicio (menú del navegador › ' +
      '“Agregar a pantalla de inicio”) y ábrala desde ahí.'
  } else if (permiso === 'denied') {
    texto = 'Bloqueó las notificaciones. Actívelas en los ajustes del navegador para recibir los avisos.'
  }
  return (
    <section className="tarjeta-app activar-avisos">
      <span className="por-firmar-icono"><Bell size={20} aria-hidden="true" /></span>
      <div>
        <p><b>Reciba un aviso cuando su hijo ingrese, llegue tarde, falte o salga, y cuando el colegio le escriba.</b></p>
        {texto ? <p className="tenue">{texto}</p>
          : <button type="button" className="boton" onClick={activar}>Activar avisos</button>}
        {error && <p className="error">{error}</p>}
      </div>
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
      setMensaje('Listo: la próxima vez ingrese con su huella o rostro.')
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
      setMensaje('PIN cambiado. Se cerró la sesión en sus otros celulares.')
    } catch (err) { setError(err.message) }
  }

  return (
    <section className="tarjeta-app">
      <h2>Mi cuenta</h2>
      {hayPasskeys() && !yo.tiene_passkey && (
        <button type="button" className="boton secundario" onClick={registrarHuella}>
          <Fingerprint size={20} aria-hidden="true" /> Ingresar con huella en este celular
        </button>
      )}
      <form className="form-pin" onSubmit={cambiarPin}>
        <label>PIN actual
          <input type="password" inputMode="numeric" maxLength={6} required
                 value={pin.pin_actual} onChange={(e) => setPin({ ...pin, pin_actual: e.target.value })} />
        </label>
        <label>PIN nuevo
          <input type="password" inputMode="numeric" maxLength={6} required autoComplete="new-password"
                 value={pin.pin_nuevo} onChange={(e) => setPin({ ...pin, pin_nuevo: e.target.value })} />
        </label>
        <button className="boton">Cambiar PIN</button>
      </form>
      {mensaje && <p>{mensaje}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  )
}

export function fechaHora(iso) {
  return new Date(iso).toLocaleString('es-PE', { timeZone: LIMA, day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit' }).replace(/\s/g, '\u00A0')
}
