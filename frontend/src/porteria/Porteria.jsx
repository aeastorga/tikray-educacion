import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ErrorApi } from '../api.js'
import { datos, nuevoId, pendientes } from './almacen.js'
import Camara from './Camara.jsx'
import { buscar, decidir, fechaLima, horaLima, indexar, leerCodigo, minutosTarde, sinTildes } from './reglas.js'

const CADA_MS = 10000 // reintento de envío
const LOTE = 200
const TEXTO = { entrada: 'Entrada', salida: 'Salida', duplicada: 'Ya registrado' }

export default function Porteria() {
  const [padron, setPadron] = useState(null)
  const [enLinea, setEnLinea] = useState(navigator.onLine)
  const [porEnviar, setPorEnviar] = useState(0)
  const [tarjeta, setTarjeta] = useState(null)
  const [recientes, setRecientes] = useState([])
  const [camara, setCamara] = useState(false)
  const [busqueda, setBusqueda] = useState('')
  const [equipo, setEquipo] = useState(() => leerLocal('tikray.equipo') || 'Portería principal')
  const [error, setError] = useState(null)
  const lector = useRef(null)
  const marcas = useRef(new Map()) // persona -> instantes aceptados hoy en este celular
  const enviando = useRef(false)

  const indice = useMemo(() => padron && indexar(padron), [padron])

  // Padrón: el del servidor si hay internet; si no, el último guardado.
  useEffect(() => {
    api('/api/asistencia/porteria')
      .then((p) => { setPadron(p); datos.guardar('padron', p) })
      .catch(async (e) => {
        if (!(e instanceof ErrorApi)) setEnLinea(false)
        const guardado = await datos.leer('padron')
        if (guardado) setPadron(guardado)
        else setError(e instanceof ErrorApi ? e.message : 'Sin internet y sin padrón guardado: conéctate una vez para descargarlo.')
      })
    datos.leer('marcas').then((m) => {
      if (m?.fecha === fechaLima(new Date())) marcas.current = new Map(m.lista)
    })
  }, [])

  const contar = useCallback(async () => setPorEnviar((await pendientes.todos()).length), [])

  const sincronizar = useCallback(async () => {
    if (enviando.current) return
    enviando.current = true
    try {
      const lista = await pendientes.todos()
      for (let i = 0; i < lista.length; i += LOTE) {
        const r = await api('/api/asistencia/marcaciones', { metodo: 'POST', datos: { marcaciones: lista.slice(i, i + LOTE) } })
        // "error" se queda para el siguiente intento; lo demás ya lo decidió el servidor.
        await pendientes.quitar(r.resultados.filter((x) => x.estado !== 'error').map((x) => x.id_cliente))
        const rechazos = Object.fromEntries(r.resultados.filter((x) => x.estado === 'desconocido' || x.estado === 'rechazada')
          .map((x) => [x.id_cliente, x.mensaje]))
        if (Object.keys(rechazos).length) {
          setRecientes((rs) => rs.map((x) => (rechazos[x.id] ? { ...x, rechazo: rechazos[x.id] } : x)))
          setTarjeta((t) => (t && rechazos[t.id] ? { ...t, rechazo: rechazos[t.id] } : t))
        }
        setEnLinea(true)
      }
    } catch (e) {
      if (!(e instanceof ErrorApi)) setEnLinea(false)
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
    const leida = { id, persona, resultado, tarde, hora: horaLima(momento) }
    setTarjeta(leida)
    setRecientes((rs) => [leida, ...rs].slice(0, 15))
    avisar(persona ? (resultado === 'duplicada' ? 'repetida' : 'bien') : 'mal')
    contar()
    sincronizar()
  }, [padron, indice, equipo, contar, sincronizar])

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
      .filter((p) => sinTildes(p.nombre).includes(q)).slice(0, 8)
  }, [busqueda, indice])

  function manual(p) {
    if (!confirm(`¿Marcar a ${p.nombre} sin carnet?`)) return
    registrar(p, p.tipo === 'alumno' ? { alumno_id: p.id } : { usuario_id: p.id })
    setBusqueda('')
    lector.current?.focus()
  }

  if (error) return <p className="error">{error}</p>
  if (!padron) return <p className="tenue">Preparando la portería…</p>

  return (
    <div className="porteria">
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
        <Tarjeta t={tarjeta} />
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
      <table>
        <tbody>
          {recientes.map((r) => (
            <tr key={r.id ?? r.hora}>
              <td>{r.hora}</td>
              <td>{r.persona?.nombre || 'Desconocido'}</td>
              <td>{r.rechazo ? <span className="error">{r.rechazo}</span> : estadoTexto(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>

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
