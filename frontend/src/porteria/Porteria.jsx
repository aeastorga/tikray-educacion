import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ScanLine } from 'lucide-react'
import { api, ErrorApi, leerToken } from '../api.js'
import { Insignia, Persona, Tabla } from '../espacios/comun/index.js'
import { datos, nuevoId, pendientes, recojos } from './almacen.js'
import Camara from './Camara.jsx'
import Recojo, { nombreElegido } from './Recojo.jsx'
import { buscar, decidir, fechaLima, horaLima, indexar, leerCodigo, minutosTarde, sinTildes } from './reglas.js'

const CADA_MS = 10000 // reintento de envío
const LOTE = 200
const TEXTO = { entrada: 'Entrada', salida: 'Salida', duplicada: 'Ya registrado' }

// Quién puede recogerlo hoy según el padrón del celular. Las autorizaciones "solo hoy" de un padrón de otro día
// ya no valen (la respuesta del servidor trae la lista al día cuando hay internet).
function listaDelDia(padron, alumnoId) {
  const lista = padron.recojo?.[alumnoId]
  if (!lista) return { personas: [] }
  if (fechaLima(new Date(padron.generado_en)) === fechaLima(new Date())) return lista
  return { ...lista, personas: lista.personas.filter((p) => p.tipo !== 'del_dia') }
}

export default function Porteria({ yo }) {
  const [padron, setPadron] = useState(null)
  const [enLinea, setEnLinea] = useState(navigator.onLine)
  const [porEnviar, setPorEnviar] = useState(0)
  const [tarjeta, setTarjeta] = useState(null)
  const [salida, setSalida] = useState(null) // recojo seguro: la última salida de un alumno y quién lo recoge
  const [recientes, setRecientes] = useState([])
  const [camara, setCamara] = useState(false)
  const [busqueda, setBusqueda] = useState('')
  const [equipo, setEquipo] = useState(() => leerLocal('tikray.equipo') || 'Portería principal')
  const [error, setError] = useState(null)
  const [sesionVencida, setSesionVencida] = useState(!leerToken())
  const lector = useRef(null)
  const marcas = useRef(new Map()) // persona -> instantes aceptados hoy en este celular
  const enviando = useRef(false)

  const indice = useMemo(() => padron && indexar(padron), [padron])

  // Padrón: el del servidor si hay internet; si no, el último guardado.
  useEffect(() => {
    api('/api/asistencia/porteria', { sinSalir: true })
      .then((p) => { setPadron(p); datos.guardar('padron', p) })
      .catch(async (e) => {
        if (!(e instanceof ErrorApi)) setEnLinea(false)
        if (e.estado === 401) setSesionVencida(true)
        const guardado = await datos.leer('padron')
        if (guardado) setPadron(guardado)
        else setError(e.estado === 401 ? 'Tu sesión venció. Vuelve a ingresar para descargar el padrón.'
          : e instanceof ErrorApi ? e.message : 'Sin internet y sin padrón guardado: conéctate una vez para descargarlo.')
      })
    datos.leer('marcas').then((m) => {
      if (m?.fecha === fechaLima(new Date())) marcas.current = new Map(m.lista)
    })
  }, [])

  const contar = useCallback(async () => {
    const [m, r] = await Promise.all([pendientes.todos(), recojos.todos().catch(() => [])])
    setPorEnviar(m.length + r.length)
  }, [])

  const sincronizar = useCallback(async () => {
    if (enviando.current || !leerToken()) return
    enviando.current = true
    try {
      const lista = await pendientes.todos()
      for (let i = 0; i < lista.length; i += LOTE) {
        const r = await api('/api/asistencia/marcaciones',
          { metodo: 'POST', datos: { marcaciones: lista.slice(i, i + LOTE) }, sinSalir: true })
        // "error" se queda para el siguiente intento; lo demás ya lo decidió el servidor.
        await pendientes.quitar(r.resultados.filter((x) => x.estado !== 'error').map((x) => x.id_cliente))
        const rechazos = Object.fromEntries(r.resultados.filter((x) => x.estado === 'desconocido' || x.estado === 'rechazada')
          .map((x) => [x.id_cliente, x.mensaje]))
        if (Object.keys(rechazos).length) {
          setRecientes((rs) => rs.map((x) => (rechazos[x.id] ? { ...x, rechazo: rechazos[x.id] } : x)))
          setTarjeta((t) => (t && rechazos[t.id] ? { ...t, rechazo: rechazos[t.id] } : t))
          // Una salida rechazada no tiene recojo que registrar.
          await recojos.quitar(Object.keys(rechazos)).catch(() => {})
          setSalida((x) => (x && rechazos[x.id] ? null : x))
        }
        // Quién puede recogerlo, al día (pudieron autorizar a alguien después de bajar el padrón).
        const listas = Object.fromEntries(r.resultados.filter((x) => x.recojo).map((x) => [x.id_cliente, x.recojo]))
        if (Object.keys(listas).length) setSalida((x) => (x && listas[x.id] ? { ...x, lista: listas[x.id] } : x))
        // Un permiso de salida que el padrón del celular aún no tenía (lo pidieron después).
        const permisos = Object.fromEntries(r.resultados.filter((x) => x.permiso_salida)
          .map((x) => [x.id_cliente, x.permiso_salida]))
        if (Object.keys(permisos).length) {
          setTarjeta((t) => (t && permisos[t.id] && !t.permiso ? { ...t, permiso: permisos[t.id] } : t))
        }
        setEnLinea(true)
      }
      // Después de las marcaciones: quién recogió a cada alumno. "esperando" (su salida aún no llegó) y
      // "error" se quedan para el siguiente intento.
      const porRecoger = await recojos.todos().catch(() => [])
      for (let i = 0; i < porRecoger.length; i += LOTE) {
        const r = await api('/api/recojo/registros',
          { metodo: 'POST', datos: { recojos: porRecoger.slice(i, i + LOTE).map(({ nombre, fuera_de_lista, ...x }) => x) }, sinSalir: true })
        await recojos.quitar(r.resultados.filter((x) => x.estado === 'ok' || x.estado === 'rechazada').map((x) => x.marcacion))
        const fuera = Object.fromEntries(r.resultados.filter((x) => x.estado === 'ok').map((x) => [x.marcacion, x.fuera_de_lista]))
        setSalida((x) => (x?.elegido && x.id in fuera ? { ...x, elegido: { ...x.elegido, fuera_de_lista: fuera[x.id] } } : x))
      }
    } catch (e) {
      if (!(e instanceof ErrorApi)) setEnLinea(false)
      if (e.estado === 401) setSesionVencida(true) // las pendientes siguen en el celular
    } finally {
      enviando.current = false
      contar()
    }
  }, [contar])

  useEffect(() => {
    contar()
    sincronizar()
    const intervalo = setInterval(sincronizar, CADA_MS)
    const conectado = () => { setEnLinea(true); sincronizar() }
    const desconectado = () => setEnLinea(false)
    window.addEventListener('online', conectado)
    window.addEventListener('offline', desconectado)
    return () => {
      clearInterval(intervalo)
      window.removeEventListener('online', conectado)
      window.removeEventListener('offline', desconectado)
    }
  }, [contar, sincronizar])

  const registrar = useCallback(async (persona, envio) => {
    const momento = new Date()
    if (persona?.tipo === 'personal' && persona.id === yo?.id) {
      setTarjeta({ id: null, persona, rechazo: 'No puedes registrar tu propia asistencia', hora: horaLima(momento) })
      avisar('mal')
      return
    }
    const clave = `${persona?.tipo}:${persona?.id}`
    let resultado = null
    let tarde = 0
    if (persona) {
      const previas = marcas.current.get(clave) || []
      resultado = decidir(previas, momento, padron.minutos_duplicado)
      if (resultado !== 'duplicada') {
        marcas.current.set(clave, [...previas, momento.getTime()])
        datos.guardar('marcas', { fecha: fechaLima(momento), lista: [...marcas.current] })
      }
      const primera = Math.min(...marcas.current.get(clave) || [momento.getTime()])
      tarde = resultado === 'entrada' ? minutosTarde(indice.turnos.get(persona.turno_id), new Date(primera)) : 0
    }
    const id = nuevoId()
    await pendientes.agregar({ id_cliente: id, momento: momento.toISOString(), equipo, ...envio })
    // Al salir, el permiso de salida del cuaderno (si el padre lo pidió para hoy).
    const permiso = persona?.tipo === 'alumno' && resultado === 'salida' ? padron.permisos_salida?.[persona.id] : null
    const leida = { id, persona, resultado, tarde, permiso, hora: horaLima(momento) }
    setTarjeta(leida)
    // Recojo seguro: al salir un alumno, quién puede recogerlo hoy. Otra lectura cierra la anterior.
    setSalida(persona?.tipo === 'alumno' && resultado === 'salida' && padron.recojo
      ? { id, persona, lista: listaDelDia(padron, persona.id), elegido: null } : null)
    setRecientes((rs) => [leida, ...rs].slice(0, 15))
    avisar(persona ? (resultado === 'duplicada' ? 'repetida' : 'bien') : 'mal')
    contar()
    sincronizar()
  }, [padron, indice, equipo, yo, contar, sincronizar])

  const leer = useCallback((texto) => {
    if (!indice) return
    const leido = leerCodigo(texto)
    if (!leido) {
      setTarjeta({ id: null, persona: null, rechazo: 'Ese código no es un carnet del colegio', hora: horaLima(new Date()) })
      avisar('mal')
      return
    }
    // Si no está en el padrón del celular (alumno recién matriculado) igual se envía: decide el servidor.
    registrar(buscar(indice, leido), { codigo: `${leido.tipo === 'personal' ? 'TK1P:' : 'TK1:'}${leido.codigo}` })
  }, [indice, registrar])

  function teclado(e) {
    if (e.key !== 'Enter') return
    e.preventDefault()
    const valor = e.currentTarget.value
    e.currentTarget.value = ''
    if (valor.trim()) leer(valor)
  }

  const resultados = useMemo(() => {
    const q = sinTildes(busqueda.trim())
    if (!indice || q.length < 2) return []
    return [...indice.alumnos.values(), ...indice.personal.values()]
      .filter((p) => !(p.tipo === 'personal' && p.id === yo?.id) && sinTildes(p.nombre).includes(q)).slice(0, 8)
  }, [busqueda, indice, yo])

  async function elegirRecojo(e) {
    const marcacion = salida.id
    const { nombre, fuera_de_lista, ...envio } = e
    await recojos.agregar({ marcacion, ...envio, nombre, fuera_de_lista })
    setSalida((x) => (x?.id === marcacion ? { ...x, elegido: e } : x))
    setRecientes((rs) => rs.map((x) => (x.id === marcacion ? { ...x, recogido: nombreElegido(e) } : x)))
    contar()
    sincronizar()
    lector.current?.focus()
  }

  function manual(p) {
    if (!confirm(`¿Marcar a ${p.nombre} sin carnet?`)) return
    registrar(p, p.tipo === 'alumno' ? { alumno_id: p.id } : { usuario_id: p.id })
    setBusqueda('')
    lector.current?.focus()
  }

  if (error) {
    return <>
      <p className="error">{error}</p>
      {sesionVencida && <Link className="boton" to="/personal?volver=/panel/asistencia/porteria">Ingresar de nuevo</Link>}
    </>
  }
  if (!padron) return <p className="tenue">Preparando la portería…</p>

  return (
    <div className="porteria">
      {sesionVencida && (
        <div className="porteria-sesion" role="alert">
          <b>Sesión vencida: vuelve a ingresar.</b>{' '}
          {porEnviar > 0
            ? (porEnviar === 1 ? 'La marcación pendiente está guardada en este celular y se enviará al ingresar.'
              : `Las ${porEnviar} marcaciones pendientes están guardadas en este celular y se enviarán al ingresar.`)
            : 'Puedes seguir marcando: se guardan en este celular y se enviarán al ingresar.'}{' '}
          <Link className="boton" to="/personal?volver=/panel/asistencia/porteria">Ingresar de nuevo</Link>
        </div>
      )}
      <div className="porteria-estado">
        <span><span className={enLinea ? 'punto en-linea' : 'punto sin-linea'} />{' '}
          {enLinea ? 'Con internet' : 'Sin internet: las marcaciones se guardan en este celular'}</span>
        <span className="tenue">{porEnviar ? `${porEnviar} por enviar` : 'Todo enviado'}</span>
        <span className="tenue">Padrón del {new Date(padron.generado_en).toLocaleString('es-PE', { timeZone: 'America/Lima' })}</span>
      </div>

      <div className="porteria-lectura">
        <div className="porteria-entrada">
          <label>Lector de carnets
            <input ref={lector} autoFocus placeholder="Escanea el carnet o escribe el código y pulsa Enter"
                   onKeyDown={teclado} autoComplete="off" autoCapitalize="characters" />
          </label>
          <button className="boton secundario" onClick={() => setCamara(!camara)}>
            {camara ? 'Apagar cámara' : 'Usar cámara'}
          </button>
          {camara && <Camara alLeer={leer} />}
        </div>
        <div className="porteria-derecha">
          <Tarjeta t={tarjeta} />
          {salida && <Recojo key={salida.id} alumno={salida.persona} lista={salida.lista} elegido={salida.elegido}
                             alElegir={elegirRecojo} />}
        </div>
      </div>

      <h3>Marcar sin carnet</h3>
      <input className="porteria-buscar" placeholder="Busca por apellido o nombre" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
      {resultados.length > 0 && (
        <ul className="porteria-busqueda">
          {resultados.map((p) => (
            <li key={`${p.tipo}${p.id}`}>
              <span>{p.nombre} <span className="tenue">{p.tipo === 'alumno' ? p.seccion : 'Personal'}</span></span>
              <button className="boton" onClick={() => manual(p)}>Marcar</button>
            </li>
          ))}
        </ul>
      )}

      <h3>Últimas lecturas</h3>
      <Tabla etiqueta="Últimas lecturas" filas={recientes} clave={(r) => r.id ?? r.hora}
             vacio={{ icono: ScanLine, titulo: 'Todavía no hay lecturas', texto: 'Las marcaciones de este celular aparecen aquí.' }}
             columnas={[
               { id: 'persona', titulo: 'Persona', celda: (r) => (
                 <Persona nombre={r.persona?.nombre || 'Desconocido'}
                          detalle={r.persona ? [r.persona.tipo === 'alumno' ? r.persona.seccion : 'Personal',
                            r.recogido && `Con ${r.recogido}`].filter(Boolean).join(' · ') : null} />
               ) },
               { id: 'hora', titulo: 'Hora', numero: true, alinear: 'derecha', celda: (r) => r.hora },
               { id: 'estado', titulo: 'Estado', nowrap: true, celda: (r) => <EstadoLectura r={r} /> },
             ]} />

      <details className="porteria-ajustes">
        <summary>Ajustes de este celular</summary>
        <label>Nombre de esta portería
          <input value={equipo} maxLength={60}
                 onChange={(e) => { setEquipo(e.target.value); guardarLocal('tikray.equipo', e.target.value) }} />
        </label>
      </details>
    </div>
  )
}

function estadoTexto(r) {
  if (!r.persona) return 'Se envía para revisar'
  return `${TEXTO[r.resultado]}${r.tarde ? ` · tarde ${duracion(r.tarde)}` : ''}`
}

function EstadoLectura({ r }) {
  if (r.rechazo) return <Insignia tono="falta">{r.rechazo}</Insignia>
  if (!r.persona) return <Insignia tono="neutro">Se envía para revisar</Insignia>
  if (r.resultado === 'entrada') {
    return r.tarde ? <Insignia tono="tarde">Tarde · {duracion(r.tarde)}</Insignia> : <Insignia tono="bien">A tiempo</Insignia>
  }
  return <Insignia tono={r.resultado === 'salida' ? 'info' : 'neutro'}>{TEXTO[r.resultado]}</Insignia>
}

function duracion(minutos) {
  return minutos < 60 ? `${minutos} min` : `${Math.floor(minutos / 60)} h ${minutos % 60} min`
}

function Tarjeta({ t }) {
  if (!t) return <div className="porteria-tarjeta vacia">Esperando carnet…</div>
  const clase = t.rechazo || !t.persona ? 'mal' : t.resultado === 'duplicada' ? 'repetida' : t.tarde ? 'tarde' : 'bien'
  return (
    <div className={`porteria-tarjeta ${clase}`} role="status" aria-live="assertive">
      <div className="porteria-hora">{t.hora}</div>
      <div className="porteria-nombre">{t.persona?.nombre || 'Carnet no reconocido'}</div>
      {t.persona && <div>{t.persona.tipo === 'alumno' ? t.persona.seccion : 'Personal'}</div>}
      <div className="porteria-resultado">
        {t.rechazo || (t.persona ? estadoTexto(t) : 'No está en el padrón de este celular; se enviará para revisar')}
      </div>
      {t.permiso && (
        <div className="porteria-permiso">
          Permiso de salida {t.permiso.hora} · Recoge: {t.permiso.recoge}
          {t.permiso.estado !== 'aprobada' && <b> · Aún sin aprobar por el colegio</b>}
          <div>{t.permiso.motivo}</div>
        </div>
      )}
    </div>
  )
}

let audio = null
function avisar(tipo) {
  try {
    navigator.vibrate?.(tipo === 'mal' ? [80, 60, 80] : 60)
    audio ??= new AudioContext()
    const o = audio.createOscillator()
    const g = audio.createGain()
    o.frequency.value = tipo === 'bien' ? 880 : tipo === 'repetida' ? 600 : 220
    g.gain.value = 0.15
    o.connect(g).connect(audio.destination)
    o.start()
    o.stop(audio.currentTime + (tipo === 'mal' ? 0.35 : 0.12))
  } catch { /* sin sonido no pasa nada */ }
}

function leerLocal(clave) {
  try { return localStorage.getItem(clave) } catch { return null }
}

function guardarLocal(clave, valor) {
  try { localStorage.setItem(clave, valor) } catch { /* modo privado */ }
}
