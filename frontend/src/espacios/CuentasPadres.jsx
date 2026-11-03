import { ArrowLeft } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'
import { api } from '../api.js'
import './familia.css'

const ESTADO = { sin_cuenta: 'Sin cuenta', pendiente: 'Por aprobar', activo: 'Activa', bloqueado: 'Bloqueada' }
const NOTIFICACIONES = { sin_app: 'No entró a la app', sin_permiso: 'Sin notificaciones', activas: 'Recibe avisos' }
const ENLACE = { pendiente: 'Enviado', usada: 'Usado', anulada: 'Anulado', bloqueada: 'Bloqueado', vencida: 'Vencido' }
const ENTREGA = { enviado: 'Le llegó', sin_notificaciones: 'Sin notificaciones', error: 'No se pudo entregar' }
const ORIGEN = { excel: 'Carga de Excel', panel: 'Panel', familia: 'El apoderado' }

export default function CuentasPadres({ colegio, editar, reglas }) {
  return (
    <Routes>
      <Route index element={<Lista colegio={colegio} editar={editar} reglas={reglas} />} />
      <Route path=":id" element={<Detalle />} />
    </Routes>
  )
}

function Etiqueta({ valor, textos }) {
  return <span className={`etiqueta ${valor}`}>{textos[valor] || valor}</span>
}

function Lista({ colegio, editar, reglas }) {
  const [lista, setLista] = useState(null)
  const [q, setQ] = useState('')
  const [estado, setEstado] = useState('')
  const [activacion, setActivacion] = useState(null)
  const [enlace, setEnlace] = useState(null)
  const [error, setError] = useState(null)

  const cargar = useCallback(() => {
    const p = new URLSearchParams({ q, ...(estado && { estado }) })
    return api(`/api/familias/apoderados?${p}`).then(setLista).catch((e) => setError(e.message))
  }, [q, estado])
  useEffect(() => {
    const t = setTimeout(cargar, 250)
    return () => clearTimeout(t)
  }, [cargar])
  useEffect(() => { api('/api/familias/configuracion').then((c) => setActivacion(c.activacion)) }, [])

  async function accion(a, ruta, datos) {
    setError(null)
    try {
      const r = await api(`/api/familias/apoderados/${a.id}/${ruta}`, { metodo: 'POST', datos })
      if (ruta === 'invitacion') setEnlace({ ...r, nombre: a.nombre })
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function cambiarActivacion(valor) {
    setError(null)
    try {
      setActivacion((await api('/api/familias/configuracion', { metodo: 'PUT', datos: { activacion: valor } })).activacion)
    } catch (err) { setError(err.message) }
  }

  const resumen = lista && {
    activas: lista.filter((a) => a.estado === 'activo').length,
    avisos: lista.filter((a) => a.notificaciones === 'activas').length,
    porAprobar: lista.filter((a) => a.estado === 'pendiente').length,
  }

  return (
    <>
      <h2>Cuentas de padres</h2>
      {resumen && (
        <p className="tenue">
          {lista.length} apoderados · {resumen.activas} con cuenta activa · {resumen.avisos} reciben avisos
          {resumen.porAprobar > 0 && <> · <b>{resumen.porAprobar} por aprobar</b></>}
        </p>
      )}
      {activacion && (
        <label className="casilla">
          <input type="checkbox" checked={activacion === 'aprobacion'} disabled={!reglas}
                 onChange={(e) => cambiarActivacion(e.target.checked ? 'aprobacion' : 'automatica')} />
          Aprobar cada cuenta antes de que el padre pueda ver a su hijo
          {!reglas && <span className="tenue"> (lo cambia quien edita la configuración)</span>}
        </label>
      )}
      {enlace && <EnlaceGenerado enlace={enlace} colegio={colegio} cerrar={() => setEnlace(null)} />}
      <div className="fila-form">
        <input placeholder="Buscar por nombre o DNI" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={estado} onChange={(e) => setEstado(e.target.value)}>
          <option value="">Todas</option>
          {Object.entries(ESTADO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {lista && (
        <table>
          <thead>
            <tr><th>Apoderado</th><th>Hijos</th><th>Cuenta</th><th>Avisos</th><th>Enlace</th><th></th></tr>
          </thead>
          <tbody>
            {lista.map((a) => (
              <tr key={a.id}>
                <td>
                  <Link to={`${a.id}`}>{a.nombre}</Link>
                  <div className="tenue">{a.documento}{a.celular && ` · ${a.celular}`}</div>
                </td>
                <td>{a.hijos.join(', ')}</td>
                <td><Etiqueta valor={a.estado} textos={ESTADO} /></td>
                <td>
                  <Etiqueta valor={a.notificaciones} textos={NOTIFICACIONES} />
                  {a.ultimo_aviso && (
                    <div className="tenue" title={a.ultimo_aviso.cuerpo}>
                      Último: {ENTREGA[a.ultimo_aviso.estado]}, {fechaHora(a.ultimo_aviso.creado_en)}
                    </div>
                  )}
                </td>
                <td>
                  {a.invitacion ? <>{ENLACE[a.invitacion.estado]}
                    <div className="tenue">{fechaHora(a.invitacion.creado_en)}</div></> : <span className="tenue">—</span>}
                </td>
                <td>
                  {editar && (
                    <div className="acciones">
                      {a.estado === 'sin_cuenta' && (
                        <button className="enlace" onClick={() => accion(a, 'invitacion', {})}>
                          {a.invitacion ? 'Nuevo enlace' : 'Enviar enlace'}
                        </button>
                      )}
                      {(a.estado === 'activo' || a.estado === 'pendiente') && (
                        <button className="enlace" onClick={() => accion(a, 'invitacion', { nuevo_pin: true })}>
                          Enlace para nuevo PIN
                        </button>
                      )}
                      {a.estado === 'pendiente' && (
                        <button className="enlace" onClick={() => accion(a, 'aprobar')}>Aprobar</button>
                      )}
                      {a.estado === 'bloqueado' ? (
                        <button className="enlace" onClick={() => accion(a, 'desbloquear')}>Desbloquear</button>
                      ) : (
                        <button className="enlace" onClick={() => {
                          if (confirm(`¿Bloquear el acceso de ${a.nombre}? Se cierran sus sesiones y se anula su enlace.`)) {
                            accion(a, 'bloquear')
                          }
                        }}>Bloquear</button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

// El token solo se ve una vez: aquí se arma el enlace y el mensaje para WhatsApp.
export function EnlaceGenerado({ enlace, colegio, cerrar, vence = 'Vence en 7 días' }) {
  const url = `${window.location.origin}/familia/activar#${enlace.token}`
  const mensaje = `Hola ${enlace.nombres}, este es tu enlace personal para activar tu cuenta de ${colegio.nombre} ` +
    `y recibir los avisos de asistencia de tu hijo o hija: ${url}\n\nTe pedirá tu DNI y el de tu hijo o hija. ` +
    `${vence} y solo sirve una vez. No lo compartas.`
  const numero = enlace.celular?.replace(/\D/g, '')
  const wa = numero && `https://wa.me/${numero.length === 9 ? `51${numero}` : numero}?text=${encodeURIComponent(mensaje)}`
  const [copiado, setCopiado] = useState(false)

  async function copiar() {
    try { await navigator.clipboard.writeText(mensaje); setCopiado(true) } catch { /* sin permiso: queda el campo */ }
  }

  return (
    <div className="aviso enlace-generado">
      <b>Enlace para {enlace.nombre}</b>
      <span className="tenue">Envíalo desde el WhatsApp del colegio. Solo se muestra ahora; si lo pierdes, genera otro.</span>
      <input readOnly value={url} onFocus={(e) => e.target.select()} />
      <div className="acciones">
        {wa ? <a className="boton" href={wa} target="_blank" rel="noreferrer">Enviar por WhatsApp</a>
          : <span className="tenue">No tiene celular registrado: copia el mensaje o imprime su carta.</span>}
        <button className="boton secundario" onClick={copiar}>{copiado ? 'Copiado' : 'Copiar mensaje'}</button>
        <button className="enlace" onClick={cerrar}>Cerrar</button>
      </div>
    </div>
  )
}

function Detalle() {
  const { id } = useParams()
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => api(`/api/familias/apoderados/${id}`).then(setD).catch((e) => setError(e.message)), [id])
  useEffect(() => { cargar() }, [cargar])

  async function cerrarSesiones() {
    try { await api(`/api/familias/apoderados/${id}/cerrar-sesiones`, { metodo: 'POST' }); cargar() } catch (e) { setError(e.message) }
  }

  if (error) return <p className="error">{error}</p>
  if (!d) return <p className="tenue">Cargando…</p>
  return (
    <div className="detalle-apoderado">
      <div>
        <Link to=".." relative="path" className="enlace"><ArrowLeft size={18} aria-hidden="true" /> Cuentas de padres</Link>
        <h2>{d.nombre}</h2>
        <p>
          <Etiqueta valor={d.estado} textos={ESTADO} /> <Etiqueta valor={d.notificaciones} textos={NOTIFICACIONES} />
          {d.dispositivos > 0 && <span className="tenue"> en {d.dispositivos} {d.dispositivos === 1 ? 'celular' : 'celulares'}</span>}
        </p>
        <p className="tenue">
          Celular: {d.celular || '—'}{d.activado_en && ` · Activó su cuenta el ${fechaHora(d.activado_en)}`}
        </p>
        {d.estado !== 'sin_cuenta' && <button className="enlace" onClick={cerrarSesiones}>Cerrar sus sesiones</button>}
      </div>
      <section>
        <h3>Avisos</h3>
        {d.avisos.length === 0 ? <p className="tenue">Aún no hay avisos para este apoderado.</p> : (
          <table>
            <thead><tr><th>Fecha</th><th>Aviso</th><th>Estado</th></tr></thead>
            <tbody>{d.avisos.map((a, i) => (
              <tr key={i}><td>{fechaHora(a.creado_en)}</td><td>{a.cuerpo}</td>
                <td><Etiqueta valor={a.estado} textos={ENTREGA} /></td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
      <section>
        <h3>Consentimiento (Ley 29733)</h3>
        {d.consentimientos.length === 0 ? <p className="tenue">Aún no lo da (se acepta al activar la cuenta).</p> : (
          <ul className="lista">{d.consentimientos.map((c, i) => (
            <li key={i}>Aceptó la versión {c.version} el {fechaHora(c.aceptado_en)}</li>
          ))}</ul>
        )}
      </section>
      <section>
        <h3>Enlaces enviados</h3>
        {d.invitaciones.length === 0 ? <p className="tenue">Ninguno.</p> : (
          <table>
            <thead><tr><th>Creado</th><th>Por</th><th>Estado</th><th>Intentos</th></tr></thead>
            <tbody>{d.invitaciones.map((i, n) => (
              <tr key={n}><td>{fechaHora(i.creado_en)}</td><td>{i.creado_por || '—'}</td>
                <td>{ENLACE[i.estado]}{i.motivo_anulacion && <div className="tenue">{i.motivo_anulacion}</div>}</td>
                <td>{i.intentos}</td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
      <section>
        <h3>Cambios de datos</h3>
        {d.cambios.length === 0 ? <p className="tenue">Sin cambios.</p> : (
          <table>
            <thead><tr><th>Fecha</th><th>Dato</th><th>Antes</th><th>Después</th><th>Por</th></tr></thead>
            <tbody>{d.cambios.map((c, i) => (
              <tr key={i}><td>{fechaHora(c.creado_en)}</td><td>{c.campo}</td><td>{c.antes || '—'}</td>
                <td>{c.despues}</td><td>{c.por || '—'} <span className="tenue">({ORIGEN[c.origen]})</span></td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  )
}

function fechaHora(iso) {
  return new Date(iso).toLocaleString('es-PE', { timeZone: 'America/Lima', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit' }).replace(/\s/g, '\u00A0')
}
