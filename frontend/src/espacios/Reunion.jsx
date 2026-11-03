import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, descargar } from '../api.js'
import { EnlaceGenerado } from './CuentasPadres.jsx'
import './reunion.css'

// Modo reunión, lado del tutor: abre la reunión de su aula, muestra el QR, ve llegar las fichas
// en vivo con lo que cambia frente al padrón resaltado, las aprueba (y activa la cuenta del padre
// ahí mismo) y al final ve quién faltó para mandarle su enlace por WhatsApp.

const CAMPOS = [['numero_documento', 'Documento'], ['nombres', 'Nombres'], ['apellidos', 'Apellidos'],
  ['parentesco', 'Parentesco'], ['celular', 'Celular'], ['correo', 'Correo']]
const ORIGEN = { celular: 'Su celular', quiosco: 'Tablet', papel: 'Papel' }
const ESTADO_PERSONA = { nuevo: 'Nuevo en el padrón', nuevo_vinculo: 'Ya registrado, nuevo para este alumno' }
const hora = (iso) => new Date(iso).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' })
const urlReunion = (token, quiosco = false) =>
  `${window.location.origin}/familia/reunion${quiosco ? '?quiosco=1' : ''}#${token}`

export default function Reunion({ colegio, editar }) {
  return (
    <Routes>
      <Route index element={<Inicio editar={editar} />} />
      <Route path=":id" element={<EnVivo colegio={colegio} editar={editar} />} />
    </Routes>
  )
}

function Qr({ texto, titulo }) {
  const [svg, setSvg] = useState(null)
  useEffect(() => {
    let vivo = true
    api('/api/reuniones/qr', { metodo: 'POST', datos: { texto } }).then((r) => vivo && setSvg(r.svg)).catch(() => {})
    return () => { vivo = false }
  }, [texto])
  if (!svg) return <div className="qr-reunion vacio" />
  return <img className="qr-reunion" alt={titulo} src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`} />
}

function Inicio({ editar }) {
  const navegar = useNavigate()
  const [secciones, setSecciones] = useState([])
  const [recientes, setRecientes] = useState([])
  const [horas, setHoras] = useState(3)
  const [error, setError] = useState(null)

  useEffect(() => {
    api('/api/reuniones/secciones').then(setSecciones).catch((e) => setError(e.message))
    api('/api/reuniones').then(setRecientes).catch(() => {})
  }, [])

  async function abrir(s) {
    setError(null)
    try {
      const r = await api('/api/reuniones', { metodo: 'POST', datos: { seccion_id: s.id, horas: Number(horas) } })
      navegar(`/panel/reunion/${r.id}`)
    } catch (err) { setError(err.message) }
  }

  async function pdf(s) {
    try { await descargar(`/api/reuniones/secciones/${s.id}/fichas.pdf`, `fichas-${s.nombre}.pdf`) }
    catch (err) { setError(err.message) }
  }

  return (
    <div>
      <h2>Reunión de padres</h2>
      <p className="tenue">Abre la reunión de tu aula y muestra el QR: cada padre llena su ficha desde su celular y
        tú la apruebas ahí mismo. El QR solo sirve para los alumnos de esa aula y vence en unas horas.</p>
      {error && <p className="error">{error}</p>}
      {editar && (
        <label className="en-linea">Duración del QR
          <select value={horas} onChange={(e) => setHoras(e.target.value)}>
            {[1, 2, 3, 4, 6, 8].map((h) => <option key={h} value={h}>{h} {h === 1 ? 'hora' : 'horas'}</option>)}
          </select>
        </label>
      )}
      <ul className="lista-secciones">
        {secciones.map((s) => (
          <li key={s.id}>
            <b>{s.nombre}</b>
            <span className="acciones">
              {s.reunion_abierta ? <Link className="boton" to={`/panel/reunion/${s.reunion_abierta}`}>Continuar reunión</Link>
                : editar && <button className="boton" onClick={() => abrir(s)}>Abrir reunión</button>}
              <button className="enlace" onClick={() => pdf(s)}>Fichas en PDF</button>
            </span>
          </li>
        ))}
        {!secciones.length && <li className="tenue">No tienes secciones a tu cargo en el año activo.</li>}
      </ul>
      {recientes.length > 0 && (
        <>
          <h3>Reuniones recientes</h3>
          <table>
            <thead><tr><th>Sección</th><th>Fecha</th><th>Estado</th><th>Fichas</th></tr></thead>
            <tbody>
              {recientes.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/panel/reunion/${r.id}`}>{r.seccion}</Link></td>
                  <td>{new Date(r.creado_en).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })}</td>
                  <td><span className={`etiqueta ${r.estado}`}>{r.estado}</span></td>
                  <td>{r.fichas.aprobada || 0} aprobadas · {r.fichas.pendiente || 0} pendientes</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

function EnVivo({ colegio, editar }) {
  const { id } = useParams()
  const [r, setR] = useState(null)
  const [vista, setVista] = useState('fichas')
  const [error, setError] = useState(null)
  const [activacion, setActivacion] = useState(null)
  const vistas = useRef(null)  // ids ya vistos: las fichas que llegan después se resaltan
  const [nuevas, setNuevas] = useState(new Set())

  const cargar = useCallback(() => api(`/api/reuniones/${id}`).then((d) => {
    const llaves = d.fichas.map((f) => `${f.id}:${f.actualizado_en}`)
    if (vistas.current) {
      const recien = llaves.filter((k) => !vistas.current.has(k))
      if (recien.length) setNuevas((n) => new Set([...n, ...recien.map((k) => Number(k.split(':')[0]))]))
    }
    vistas.current = new Set(llaves)
    setR(d)
  }).catch((e) => setError(e.message)), [id])

  useEffect(() => {
    cargar()
    const t = setInterval(cargar, 4000)
    return () => clearInterval(t)
  }, [cargar])

  async function accion(ruta, datos) {
    setError(null)
    try {
      const res = await api(`/api/reuniones/${id}${ruta}`, { metodo: 'POST', datos })
      await cargar()
      return res
    } catch (err) { setError(err.message) }
  }

  async function aprobar(f, activar) {
    const res = await accion(`/fichas/${f.id}/aprobar`, { activar })
    if (!res) return
    setNuevas((n) => { const c = new Set(n); c.delete(f.id); return c })
    if (res.notas.length) setError(res.notas.join(' '))
    if (res.activacion?.token) setActivacion({ ...res.activacion, alumno: f.alumno })
  }

  async function rechazar(f) {
    const motivo = prompt('¿Por qué no se aprueba? El padre lo verá en su celular.')
    if (motivo) await accion(`/fichas/${f.id}/rechazar`, { motivo })
  }

  if (!r) return <p className="tenue">{error || 'Cargando…'}</p>
  const pendientes = r.fichas.filter((f) => f.estado === 'pendiente')
  const revisadas = r.fichas.filter((f) => f.estado !== 'pendiente')

  return (
    <div className="reunion">
      <p><Link to="/panel/reunion" className="enlace">← Reuniones</Link></p>
      <h2>{r.titulo} · {r.seccion}</h2>
      <p className="tenue">
        <span className={`etiqueta ${r.estado}`}>{r.estado}</span>{' '}
        {r.estado === 'abierta' ? `El QR vence a las ${hora(r.vence_en)}` : `Abierta a las ${hora(r.creado_en)}`}
        {' · '}{r.fichas.filter((f) => f.estado === 'aprobada').length} de {r.alumnos} alumnos con ficha aprobada
      </p>
      {error && <p className="error">{error}</p>}

      {activacion && (
        <div className="aviso activacion-reunion">
          <b>Cuenta de {activacion.nombres} lista para activar</b>
          <p className="tenue">Que escanee este código con su celular para crear su PIN, o envíale el enlace por WhatsApp.</p>
          <Qr texto={`${window.location.origin}/familia/activar#${activacion.token}`} titulo="QR para activar la cuenta" />
          <EnlaceGenerado colegio={colegio} vence="Vence en unas horas"
                          enlace={{ ...activacion, nombre: activacion.nombres }} cerrar={() => setActivacion(null)} />
        </div>
      )}

      <div className="reunion-cuerpo">
        {r.estado === 'abierta' && r.token && (
          <aside className="reunion-qr">
            <Qr texto={urlReunion(r.token)} titulo={`QR de la reunión de ${r.seccion}`} />
            <p>Escanea con la cámara del celular</p>
            {editar && (
              <div className="acciones apiladas">
                <a className="boton secundario" href={urlReunion(r.token, true)} target="_blank" rel="noreferrer">
                  Abrir en la tablet (modo quiosco)</a>
                <button className="enlace" onClick={() => confirm('El QR actual dejará de servir. ¿Generar otro?') && accion('/nuevo-qr')}>
                  Generar otro QR</button>
                <button className="enlace" onClick={() => confirm('¿Cerrar la reunión? El QR dejará de servir.') && accion('/cerrar')}>
                  Cerrar reunión</button>
              </div>
            )}
          </aside>
        )}
        {r.estado === 'bloqueada' && editar && (
          <aside className="reunion-qr">
            <p>El QR se bloqueó por muchos documentos equivocados.</p>
            <button className="boton" onClick={() => accion('/nuevo-qr')}>Mostrar un QR nuevo</button>
          </aside>
        )}

        <section className="reunion-fichas">
          <nav className="subpestanas">
            <button className={vista === 'fichas' ? 'activa' : ''} onClick={() => setVista('fichas')}>
              Fichas {pendientes.length > 0 && <span className="contador">{pendientes.length}</span>}</button>
            <button className={vista === 'faltan' ? 'activa' : ''} onClick={() => setVista('faltan')}>Quién faltó</button>
            {editar && <button className={vista === 'papel' ? 'activa' : ''} onClick={() => setVista('papel')}>Ficha en papel</button>}
          </nav>
          {vista === 'fichas' && (
            <>
              {!r.fichas.length && <p className="tenue">Aún no llegan fichas. Esta lista se actualiza sola.</p>}
              {pendientes.map((f) => (
                <FichaPendiente key={f.id} f={f} nueva={nuevas.has(f.id)} editar={editar}
                                aprobar={aprobar} rechazar={rechazar} />
              ))}
              {revisadas.length > 0 && <h3>Revisadas</h3>}
              <ul className="fichas-revisadas">
                {revisadas.map((f) => (
                  <li key={f.id}>
                    <span>{f.alumno} · {f.datos.apoderado.nombres} {f.datos.apoderado.apellidos}</span>
                    <span>
                      <span className={`etiqueta ${f.estado === 'aprobada' ? 'activo' : 'bloqueado'}`}>{f.estado}</span>{' '}
                      {f.cuenta && <span className="tenue">cuenta: {f.cuenta.replace('_', ' ')}</span>}
                      {f.motivo_rechazo && <span className="tenue">{f.motivo_rechazo}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {vista === 'faltan' && <Faltan id={id} colegio={colegio} editar={editar} />}
          {vista === 'papel' && <Papel id={id} listo={() => { setVista('fichas'); cargar() }} />}
        </section>
      </div>
    </div>
  )
}

function FichaPendiente({ f, nueva, editar, aprobar, rechazar }) {
  const [activar, setActivar] = useState(true)
  const [enviando, setEnviando] = useState(false)
  async function ok() {
    setEnviando(true)
    try { await aprobar(f, activar) } finally { setEnviando(false) }
  }
  return (
    <article className={`ficha-reunion${nueva ? ' nueva' : ''}`}>
      <header>
        <b>{f.alumno}</b>
        <span className="tenue">{ORIGEN[f.origen]} · {hora(f.actualizado_en)}{f.reenviada ? ' · corregida' : ''}</span>
      </header>
      <Persona titulo="Quien llena" datos={f.datos.apoderado} cambios={f.apoderado} />
      {f.datos.otro && <Persona titulo="Otro apoderado" datos={f.datos.otro} cambios={f.otro} />}
      {editar && (
        <div className="acciones">
          <button className="boton" disabled={enviando} onClick={ok}>Aprobar</button>
          <label className="casilla en-linea">
            <input type="checkbox" checked={activar} onChange={(e) => setActivar(e.target.checked)} />
            Activar su cuenta ahora
          </label>
          <button className="enlace" onClick={() => rechazar(f)}>Rechazar</button>
        </div>
      )}
      <p className="tenue chico">Aprueba solo con el padre o la madre delante y su documento a la vista.</p>
    </article>
  )
}

function Persona({ titulo, datos, cambios }) {
  const distinto = cambios?.cambios || {}
  return (
    <div className="ficha-bloque">
      <div className="ficha-titulo">
        <span>{titulo}</span>
        {cambios && cambios.estado !== 'registrado' && <span className="etiqueta pendiente">{ESTADO_PERSONA[cambios.estado]}</span>}
        {cambios?.con_cuenta && titulo !== 'Quien llena' && <span className="tenue">tiene cuenta: su contacto no se cambia</span>}
      </div>
      <dl>
        {CAMPOS.map(([clave, etiqueta]) => {
          const valor = clave === 'numero_documento' ? `${datos.tipo_documento} ${datos.numero_documento}` : datos[clave]
          if (!valor) return null
          const cambio = distinto[clave]
          return (
            <div key={clave} className={cambio ? 'cambio' : ''}>
              <dt>{etiqueta}</dt>
              <dd>{cambio && cambio[0] ? <><del>{cambio[0]}</del> <mark>{valor}</mark></> : cambio ? <mark>{valor}</mark> : valor}</dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}

function Faltan({ id, colegio, editar }) {
  const [lista, setLista] = useState(null)
  const [enlace, setEnlace] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { api(`/api/reuniones/${id}/ausentes`).then(setLista).catch((e) => setError(e.message)) }, [id])

  async function invitar(p) {
    setError(null)
    try {
      const r = await api(`/api/reuniones/${id}/apoderados/${p.id}/invitacion`, { metodo: 'POST' })
      setEnlace({ ...r, nombre: p.nombre })
    } catch (err) { setError(err.message) }
  }

  if (!lista) return <p className="tenue">{error || 'Cargando…'}</p>
  return (
    <div>
      {error && <p className="error">{error}</p>}
      {enlace && <EnlaceGenerado enlace={enlace} colegio={colegio} cerrar={() => setEnlace(null)} />}
      {!lista.length && <p>Todos los alumnos tienen su ficha.</p>}
      <ul className="lista-faltan">
        {lista.map((a) => (
          <li key={a.id}>
            <b>{a.nombre}</b>
            {!a.apoderados.length && <span className="tenue">Sin apoderados en el padrón</span>}
            {a.apoderados.map((p) => (
              <div key={p.id} className="faltan-apoderado">
                <span>{p.nombre} <span className="tenue">({p.parentesco})</span></span>
                <span className={`etiqueta ${p.estado}`}>{p.estado.replace('_', ' ')}</span>
                {editar && p.estado !== 'activo' && p.estado !== 'bloqueado' && (
                  <button className="enlace" onClick={() => invitar(p)}>Enviar su enlace</button>
                )}
              </div>
            ))}
          </li>
        ))}
      </ul>
    </div>
  )
}

const VACIA = { tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '', celular: '', correo: '',
  parentesco: 'Madre' }

// La ficha impresa que el padre firmó: el tutor la pasa y queda pendiente como las demás.
function Papel({ id, listo }) {
  const [alumnos, setAlumnos] = useState([])
  const [alumno, setAlumno] = useState('')
  const [p, setP] = useState({ ...VACIA })
  const [firmo, setFirmo] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    // Solo los alumnos que aún no tienen ficha en esta reunión.
    api(`/api/reuniones/${id}/ausentes`).then(setAlumnos).catch((e) => setError(e.message))
  }, [id])

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    try {
      await api(`/api/reuniones/${id}/fichas`, { metodo: 'POST', datos: {
        alumno_id: Number(alumno), apoderado: { ...p, correo: p.correo || null }, acepto: firmo } })
      listo()
    } catch (err) { setError(err.message) }
  }

  const campo = (c) => (e) => setP({ ...p, [c]: e.target.value })
  return (
    <form className="formulario" onSubmit={guardar}>
      <label>Alumno
        <select value={alumno} required onChange={(e) => setAlumno(e.target.value)}>
          <option value="">Elige…</option>
          {alumnos.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
        </select>
      </label>
      <div className="ficha-campos">
        <label>Tipo de documento
          <select value={p.tipo_documento} onChange={campo('tipo_documento')}>
            {['DNI', 'CE', 'PAS', 'OTRO'].map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Número<input value={p.numero_documento} required onChange={campo('numero_documento')} /></label>
        <label>Nombres<input value={p.nombres} required onChange={campo('nombres')} /></label>
        <label>Apellidos<input value={p.apellidos} required onChange={campo('apellidos')} /></label>
        <label>Celular<input value={p.celular} required onChange={campo('celular')} /></label>
        <label>Correo<input value={p.correo} type="email" onChange={campo('correo')} /></label>
        <label>Parentesco
          <select value={p.parentesco} onChange={campo('parentesco')}>
            {['Madre', 'Padre', 'Abuela', 'Abuelo', 'Tía', 'Tío', 'Hermana', 'Hermano', 'Apoderado', 'Otro']
              .map((x) => <option key={x}>{x}</option>)}
          </select>
        </label>
      </div>
      <label className="casilla">
        <input type="checkbox" checked={firmo} onChange={(e) => setFirmo(e.target.checked)} />
        El apoderado firmó el consentimiento en la hoja (guárdala)
      </label>
      {error && <p className="error">{error}</p>}
      <button className="boton" disabled={!firmo}>Registrar ficha</button>
    </form>
  )
}
