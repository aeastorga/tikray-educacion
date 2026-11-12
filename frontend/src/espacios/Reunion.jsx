import { ArrowLeft, CalendarDays, FileDown, School } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, descargar } from '../api.js'
import { EnlaceGenerado } from './CuentasPadres.jsx'
import { Cargando, Encabezado, Insignia, Mensaje, Tabla, Vacio, fechaHora, plural, useConfirmar } from './comun/index.js'
import './reunion.css'

// Modo reunión, lado del tutor: abre la reunión de su aula, muestra el QR, ve llegar las fichas
// en vivo con lo que cambia frente al padrón resaltado, las aprueba (y activa la cuenta del padre
// ahí mismo) y al final ve quién faltó para mandarle su enlace por WhatsApp.

const CAMPOS = [['numero_documento', 'Documento'], ['nombres', 'Nombres'], ['apellidos', 'Apellidos'],
  ['parentesco', 'Parentesco'], ['celular', 'Celular'], ['correo', 'Correo']]
const CUENTA = { activo: 'Activa', pendiente: 'Por aprobar', bloqueado: 'Bloqueada', sin_cuenta: 'Sin cuenta', invitado: 'Invitado' }
const TONO_CUENTA = { activo: 'bien', pendiente: 'tarde', bloqueado: 'falta', sin_cuenta: 'neutro', invitado: 'info' }
const ORIGEN = { celular: 'Su celular', quiosco: 'Tablet', papel: 'Papel' }
const ESTADO_PERSONA = { nuevo: 'Nuevo en el padrón', nuevo_vinculo: 'Ya registrado, nuevo para este alumno' }
const hora = (iso) => new Date(iso).toLocaleTimeString('es-PE', { timeZone: 'America/Lima', hour: 'numeric', minute: '2-digit' })
  .replace(/\s/g, '\u00A0')
const ESTADO_REUNION = { abierta: ['bien', 'Abierta'], cerrada: ['neutro', 'Cerrada'], vencida: ['neutro', 'Vencida'],
  bloqueada: ['falta', 'Bloqueada'] }
export function EstadoReunion({ estado }) {
  const [tono, texto] = ESTADO_REUNION[estado] || ['neutro', estado]
  return <Insignia tono={tono}>{texto}</Insignia>
}
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
  const [secciones, setSecciones] = useState(null)
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
    const nombre = `${s.nivel}-${s.nombre}`.toLowerCase().normalize('NFD').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    try { await descargar(`/api/reuniones/secciones/${s.id}/fichas.pdf`, `fichas-${nombre}.pdf`) }
    catch (err) { setError(err.message) }
  }

  // Agrupadas por nivel, en el orden que ya trae el servidor.
  const niveles = []
  for (const s of secciones || []) {
    const ultimo = niveles[niveles.length - 1]
    if (ultimo?.nivel === s.nivel) ultimo.secciones.push(s)
    else niveles.push({ nivel: s.nivel, secciones: [s] })
  }

  return (
    <div>
      <Encabezado titulo="Reunión de padres"
                  descripcion="Abre la reunión de tu aula y muestra el QR: cada padre llena su ficha desde su celular y tú la apruebas ahí mismo."
                  acciones={editar && (
                    <label className="en-linea">Duración del QR
                      <select value={horas} onChange={(e) => setHoras(e.target.value)}>
                        {[1, 2, 3, 4, 6, 8].map((h) => <option key={h} value={h}>{plural(h, 'hora', 'horas')}</option>)}
                      </select>
                    </label>
                  )} />
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      {secciones && !secciones.length && (
        <Vacio icono={School} titulo="No tienes secciones a tu cargo" texto="Dirección asigna las secciones en Cuaderno › Docentes por sección." />
      )}
      {niveles.map((n) => (
        <section key={n.nivel} className="nivel-reunion" aria-labelledby={`nivel-${n.nivel}`}>
          <h3 id={`nivel-${n.nivel}`}>{n.nivel}</h3>
          <ul className="tarjetas-reunion">
            {n.secciones.map((s) => (
              <li key={s.id} className={s.reunion_abierta ? 'en-curso' : undefined}>
                <div className="tarjeta-reunion-cabeza">
                  <span className="seccion-grande" aria-label={`${s.nivel} · ${s.nombre}`}>{s.nombre}</span>
                  {s.reunion_abierta && <Insignia tono="bien">En curso · vence {hora(s.vence_en)}</Insignia>}
                </div>
                {s.docente && <p className="sin-margen">Docente: {s.docente}</p>}
                <p className="tenue sin-margen">
                  {plural(s.alumnos, 'alumno', 'alumnos')}
                  {s.fichas_pendientes > 0 && ` · ${plural(s.fichas_pendientes, 'ficha pendiente', 'fichas pendientes')}`}
                </p>
                <div className="acciones">
                  {s.reunion_abierta ? <Link className="boton" to={`/panel/reunion/${s.reunion_abierta}`}>Continuar reunión</Link>
                    : editar && <button className="boton" onClick={() => abrir(s)}>Abrir reunión</button>}
                  <button className="boton secundario" onClick={() => pdf(s)}><FileDown size={18} aria-hidden="true" /> Fichas en PDF</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {recientes.length > 0 && (
        <section className="nivel-reunion">
          <h3>Reuniones recientes</h3>
          <Tabla etiqueta="Reuniones recientes" filas={recientes} alFila={(r) => navegar(`/panel/reunion/${r.id}`)}
                 vacio={{ icono: CalendarDays, titulo: 'Sin reuniones recientes' }}
                 columnas={[
                   { id: 'seccion', titulo: 'Sección', celda: (r) => <Link to={`/panel/reunion/${r.id}`}>{r.seccion}</Link> },
                   { id: 'fecha', titulo: 'Fecha', nowrap: true, celda: (r) => fechaHora(r.creado_en) },
                   { id: 'estado', titulo: 'Estado', celda: (r) => <EstadoReunion estado={r.estado} /> },
                   { id: 'fichas', titulo: 'Fichas', celda: (r) => (
                     `${plural(r.fichas.aprobada || 0, 'aprobada', 'aprobadas')} · ${plural(r.fichas.pendiente || 0, 'pendiente', 'pendientes')}`
                   ) },
                 ]} />
        </section>
      )}
    </div>
  )
}

function EnVivo({ colegio, editar }) {
  const { confirmar, pedirMotivo } = useConfirmar()
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

  async function aprobar(f, activar, dniVerificado) {
    const res = await accion(`/fichas/${f.id}/aprobar`, { activar, dni_verificado: dniVerificado })
    if (!res) return
    setNuevas((n) => { const c = new Set(n); c.delete(f.id); return c })
    if (res.notas.length) setError(res.notas.join(' '))
    if (res.activacion?.token) setActivacion({ ...res.activacion, alumno: f.alumno })
  }

  async function rechazar(f) {
    const motivo = await pedirMotivo({ titulo: 'No aprobar la ficha', texto: 'El padre verá el motivo en su celular.', etiqueta: 'Motivo',
      accion: 'No aprobar', maximo: 200 })
    if (motivo) await accion(`/fichas/${f.id}/rechazar`, { motivo })
  }

  if (!r) return (error ? <Mensaje tipo="error">{error}</Mensaje> : <Cargando />)
  const pendientes = r.fichas.filter((f) => f.estado === 'pendiente')
  const revisadas = r.fichas.filter((f) => f.estado !== 'pendiente')

  return (
    <div className="reunion">
      <p><Link to="/panel/reunion" className="enlace"><ArrowLeft size={18} aria-hidden="true" /> Reuniones</Link></p>
      <h2>{r.titulo} · {r.seccion}</h2>
      <p className="tenue">
        <EstadoReunion estado={r.estado} />{' '}
        {r.estado === 'abierta' ? `El QR vence a las ${hora(r.vence_en)}` : `Abierta a las ${hora(r.creado_en)}`}
        {' · '}{r.fichas.filter((f) => f.estado === 'aprobada').length} de {plural(r.alumnos, 'alumno', 'alumnos')} con ficha aprobada
      </p>
      {error && <Mensaje tipo="error">{error}</Mensaje>}

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
                <button className="enlace" onClick={async () => { if (await confirmar({ titulo: 'Generar otro QR', texto: 'El QR actual dejará de servir.', accion: 'Generar otro', peligro: true })) accion('/nuevo-qr') }}>
                  Generar otro QR</button>
                <button className="enlace" onClick={async () => { if (await confirmar({ titulo: 'Cerrar la reunión', texto: 'El QR dejará de servir.', accion: 'Cerrar reunión', peligro: true })) accion('/cerrar') }}>
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
                      <Insignia tono={f.estado === 'aprobada' ? 'bien' : 'falta'}>{f.estado === 'aprobada' ? 'Aprobada' : 'Rechazada'}</Insignia>{' '}
                      {f.cuenta && <span className="tenue">cuenta: {f.cuenta.replace('_', ' ')}</span>}
                      {f.dni_verificado_por && <span className="tenue"> · DNI verificado por {f.dni_verificado_por} a las {hora(f.dni_verificado_en)}</span>}
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
  const [verificado, setVerificado] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const falta = f.requiere_verificacion && !verificado
  async function ok() {
    setEnviando(true)
    try { await aprobar(f, activar, f.requiere_verificacion && verificado) } finally { setEnviando(false) }
  }
  return (
    <article className={`ficha-reunion${nueva ? ' nueva' : ''}`}>
      <header>
        <b>{f.alumno}</b>
        <span className="tenue">{ORIGEN[f.origen]} · {hora(f.actualizado_en)}{f.reenviada ? ' · corregida' : ''}</span>
      </header>
      <Persona titulo="Quien llena" datos={f.datos.apoderado} cambios={f.apoderado} />
      {f.datos.otro && <Persona titulo="Otro apoderado" datos={f.datos.otro} cambios={f.otro} />}
      {editar && f.requiere_verificacion && (
        <label className={`casilla verificar-dni${verificado ? ' hecho' : ''}`}>
          <input type="checkbox" checked={verificado} onChange={(e) => setVerificado(e.target.checked)} />
          <span><b>Verifiqué su DNI en persona</b>
            <span className="tenue chico"> · La ficha suma un apoderado o cambia un celular. Queda registrado con tu nombre.</span></span>
        </label>
      )}
      {editar && (
        <div className="acciones">
          <button className="boton" disabled={enviando || falta} onClick={ok}
                  title={falta ? 'Primero marca «Verifiqué su DNI en persona»' : undefined}>Aprobar</button>
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
  const sinAplicar = cambios?.sin_aplicar || {}
  return (
    <div className="ficha-bloque">
      <div className="ficha-titulo">
        <span>{titulo}</span>
        {cambios && cambios.estado !== 'registrado' && <Insignia tono="tarde">{ESTADO_PERSONA[cambios.estado]}</Insignia>}
        {cambios?.con_cuenta && <span className="tenue">tiene cuenta: su celular y correo no se cambian aquí</span>}
      </div>
      <dl>
        {CAMPOS.map(([clave, etiqueta]) => {
          const valor = clave === 'numero_documento' ? `${datos.tipo_documento} ${datos.numero_documento}` : datos[clave]
          if (!valor) return null
          const cambio = distinto[clave]
          const ignorado = sinAplicar[clave]
          if (ignorado) {
            // Tiene cuenta propia: se ve lo que escribió, pero queda lo registrado.
            return (
              <div key={clave} className="sin-aplicar">
                <dt>{etiqueta}</dt>
                <dd>{ignorado[0] || '—'} <span className="tenue chico">(escribió {valor}; lo pide en persona en secretaría)</span></dd>
              </div>
            )
          }
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

  if (!lista) return (error ? <Mensaje tipo="error">{error}</Mensaje> : <Cargando />)
  return (
    <div>
      {error && <Mensaje tipo="error">{error}</Mensaje>}
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
                <Insignia tono={TONO_CUENTA[p.estado] || 'neutro'}>{CUENTA[p.estado] || p.estado.replace('_', ' ')}</Insignia>
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
        <label>Número<input value={p.numero_documento} required inputMode={p.tipo_documento === 'DNI' ? 'numeric' : 'text'}
                             onChange={campo('numero_documento')} /></label>
        <label>Nombres<input value={p.nombres} required onChange={campo('nombres')} /></label>
        <label>Apellidos<input value={p.apellidos} required onChange={campo('apellidos')} /></label>
        <label>Celular<input value={p.celular} required inputMode="tel" onChange={campo('celular')} /></label>
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
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      <button className="boton" disabled={!firmo}>Registrar ficha</button>
    </form>
  )
}
