import { ArrowLeft, Bell, History, Link2, UsersRound } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { Buscador, Cargando, Cifras, Encabezado, Filtros, Insignia, Mensaje, MenuAcciones, Paginacion, Persona, Selector, Tabla, documento, fechaHora, hace, plural, useConfirmar, usePaginado } from './comun/index.js'
import { Interruptor } from './Configuracion.jsx'
import './configuracion.css'
import './familia.css'

const ESTADO = { sin_cuenta: 'Sin cuenta', pendiente: 'Por aprobar', activo: 'Activa', bloqueado: 'Bloqueada' }
const TONO_ESTADO = { sin_cuenta: 'neutro', pendiente: 'tarde', activo: 'bien', bloqueado: 'falta' }
const NOTIFICACIONES = { sin_app: 'Sin app', sin_permiso: 'Sin notificaciones', activas: 'Recibe avisos' }
const TONO_NOTIF = { sin_app: 'neutro', sin_permiso: 'tarde', activas: 'bien' }
const ENLACE = { pendiente: 'Enviado', usada: 'Usado', anulada: 'Anulado', bloqueada: 'Bloqueado', vencida: 'Vencido' }
const TONO_ENLACE = { pendiente: 'info', usada: 'bien', anulada: 'neutro', bloqueada: 'falta', vencida: 'neutro' }
const ENTREGA = { enviado: 'Entregado', sin_notificaciones: 'Sin notificaciones', error: 'Falló' }
const TONO_ENTREGA = { enviado: 'bien', sin_notificaciones: 'neutro', error: 'falta' }
const ORIGEN = { excel: 'Carga de Excel', panel: 'Panel', familia: 'El apoderado' }
const FILTRO_AVISOS = { activas: 'Reciben avisos', sin_permiso: 'Sin notificaciones', sin_app: 'Sin app', error: 'Avisos fallidos hoy' }

export default function CuentasPadres({ colegio, editar, reglas }) {
  return (
    <Routes>
      <Route index element={<Lista colegio={colegio} editar={editar} reglas={reglas} />} />
      <Route path=":id" element={<Detalle />} />
    </Routes>
  )
}

function Hijos({ hijos }) {
  if (!hijos.length) return <span className="tenue">—</span>
  const texto = (h) => [h.nombres.split(' ')[0], h.seccion?.replace(' · ', ' ')].filter(Boolean).join(' · ')
  return (
    <span className="chips">
      {hijos.slice(0, 2).map((h, i) => <span key={i} className="chip-texto" title={texto(h)}>{texto(h)}</span>)}
      {hijos.length > 2 && <span className="chip-texto tenue" title={hijos.slice(2).map(texto).join(', ')}>+{hijos.length - 2} más</span>}
    </span>
  )
}

function Lista({ colegio, editar, reglas }) {
  const { confirmar } = useConfirmar()
  const navegar = useNavigate()
  const [url, setUrl] = useSearchParams()
  const [q, setQ] = useState(url.get('q') || '')
  const estado = url.get('estado') || ''
  const avisos = url.get('avisos') || ''
  const [activacion, setActivacion] = useState(null)
  const [enlace, setEnlace] = useState(null)
  const [error, setError] = useState(null)
  const { datos, error: errorLista, cargando, recargar, paginacion } =
    usePaginado('/api/familias/apoderados', { q: q.trim(), estado, avisos })

  useEffect(() => { api('/api/familias/configuracion').then((c) => setActivacion(c.activacion)).catch(() => {}) }, [])

  function filtrar(clave, valor) {
    const n = new URLSearchParams(url)
    if (valor) n.set(clave, valor); else n.delete(clave)
    setUrl(n, { replace: true })
  }

  async function accion(a, ruta, datos) {
    setError(null)
    try {
      const r = await api(`/api/familias/apoderados/${a.id}/${ruta}`, { metodo: 'POST', datos })
      if (ruta === 'invitacion') setEnlace({ ...r, nombre: a.nombre })
      recargar()
    } catch (err) { setError(err.message) }
  }

  async function bloquear(a) {
    if (await confirmar({ titulo: 'Bloquear acceso', texto: `${a.nombre} no podrá entrar a la app: se cierran sus sesiones y se anula su enlace.`,
      accion: 'Bloquear', peligro: true })) accion(a, 'bloquear')
  }

  async function cambiarActivacion(conAprobacion) {
    setError(null)
    try {
      const r = await api('/api/familias/configuracion', { metodo: 'PUT', datos: { activacion: conAprobacion ? 'aprobacion' : 'automatica' } })
      setActivacion(r.activacion)
    } catch (err) { setError(err.message) }
  }

  function acciones(a) {
    const ver = { texto: 'Ver detalle', alHacer: () => navegar(`${a.id}`) }
    if (!editar) return { principal: { texto: 'Ver', alHacer: ver.alHacer } }
    const pin = { texto: 'Enlace para nuevo PIN', alHacer: () => accion(a, 'invitacion', { nuevo_pin: true }) }
    const cerrar = { texto: 'Cerrar sus sesiones', alHacer: () => accion(a, 'cerrar-sesiones') }
    const bloq = { texto: 'Bloquear', peligro: true, alHacer: () => bloquear(a) }
    switch (a.estado) {
      case 'sin_cuenta':
        return { principal: { texto: a.invitacion ? 'Nuevo enlace' : 'Enviar enlace', alHacer: () => accion(a, 'invitacion', {}) },
          opciones: [ver, bloq] }
      case 'pendiente':
        return { principal: { texto: 'Aprobar', alHacer: () => accion(a, 'aprobar') }, opciones: [ver, pin, cerrar, bloq] }
      case 'bloqueado':
        return { principal: { texto: 'Desbloquear', alHacer: () => accion(a, 'desbloquear') }, opciones: [ver] }
      default:
        return { principal: { texto: 'Ver', alHacer: ver.alHacer }, opciones: [pin, cerrar, bloq] }
    }
  }

  const r = datos?.resumen
  const columnas = [
    { id: 'apoderado', titulo: 'Apoderado', ancho: '24%',
      celda: (a) => <Persona nombre={a.nombre} detalle={[documento(a.tipo_documento, a.numero_documento), a.celular].filter(Boolean).join(' · ')} /> },
    { id: 'hijos', titulo: 'Hijos', vacio: (a) => !a.hijos.length, celda: (a) => <Hijos hijos={a.hijos} /> },
    { id: 'cuenta', titulo: 'Cuenta', celda: (a) => <Insignia tono={TONO_ESTADO[a.estado]}>{ESTADO[a.estado]}</Insignia> },
    { id: 'avisos', titulo: 'Avisos', ocultarEnCelular: true, celda: (a) => (
      <>
        <Insignia tono={a.ultimo_aviso?.estado === 'error' ? 'falta' : TONO_NOTIF[a.notificaciones]}>
          {a.ultimo_aviso?.estado === 'error' ? 'Último falló' : NOTIFICACIONES[a.notificaciones]}
        </Insignia>
        {a.ultimo_aviso && <span className="segunda-linea" title={a.ultimo_aviso.cuerpo}>Último {hace(a.ultimo_aviso.creado_en)}</span>}
      </>
    ) },
    { id: 'enlace', titulo: 'Enlace', ocultarEnCelular: true, nowrap: true, vacio: (a) => !a.invitacion, celda: (a) => (a.invitacion ? (
      <span className="nowrap"><Insignia tono={TONO_ENLACE[a.invitacion.estado]}>{ENLACE[a.invitacion.estado]}</Insignia>{' '}
        <span className="tenue">{fechaHora(a.invitacion.creado_en)}</span></span>
    ) : <span className="tenue">—</span>) },
    { id: 'acciones', titulo: 'Acciones', acciones: true, celda: (a) => <MenuAcciones etiqueta={a.nombre} {...acciones(a)} /> },
  ]

  return (
    <>
      <Encabezado titulo="Cuentas de padres" descripcion="Invita, aprueba y bloquea el acceso de los apoderados a la app." />
      {r && (
        <Cifras items={[
          { etiqueta: 'Apoderados', valor: r.total },
          { etiqueta: 'Con cuenta activa', valor: r.activas },
          { etiqueta: 'Reciben avisos', valor: r.avisos, tono: 'bien' },
          r.por_aprobar > 0 && { etiqueta: 'Por aprobar', valor: r.por_aprobar, tono: 'tarde' },
          { etiqueta: 'Sin cuenta', valor: r.sin_cuenta },
        ]} />
      )}
      {activacion && (
        <div className="aviso aviso-interruptor">
          <div>
            <b>Aprobar cada cuenta antes de que el padre pueda ver a su hijo</b>
            <span className="tenue">{reglas ? 'Si está apagado, la cuenta se activa sola al usar el enlace.'
              : 'Lo cambia quien edita la configuración.'}</span>
          </div>
          <Interruptor etiqueta="Aprobar cada cuenta" activo={activacion === 'aprobacion'} deshabilitado={!reglas}
                       cambiar={cambiarActivacion} />
        </div>
      )}
      {enlace && <EnlaceGenerado enlace={enlace} colegio={colegio} cerrar={() => setEnlace(null)} />}
      <Filtros total={datos && plural(datos.total, 'apoderado', 'apoderados')}>
        <Buscador valor={q} cambiar={(v) => { setQ(v); filtrar('q', v.trim()) }} placeholder="Buscar por nombre, DNI o celular" />
        <Selector etiqueta="Estado de la cuenta" valor={estado} cambiar={(v) => filtrar('estado', v)}
                  opciones={[['', 'Todas las cuentas'], ...Object.entries(ESTADO)]} />
        <Selector etiqueta="Avisos" valor={avisos} cambiar={(v) => filtrar('avisos', v)}
                  opciones={[['', 'Todos los avisos'], ...Object.entries(FILTRO_AVISOS)]} />
      </Filtros>
      {(error || errorLista) && <Mensaje tipo="error">{error || errorLista}</Mensaje>}
      <Tabla etiqueta="Apoderados" columnas={columnas} filas={datos?.filas} cargando={cargando}
             alFila={(a) => navegar(`${a.id}`)}
             vacio={{ icono: UsersRound, titulo: q || estado || avisos ? 'Nadie con esos filtros' : 'Aún no hay apoderados',
               texto: q || estado || avisos ? 'Prueba con otro nombre o quita los filtros.' : 'Se cargan con el padrón (Excel o uno por uno).' }} />
      {paginacion && <Paginacion {...paginacion} />}
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
      <input aria-label="Enlace de activación" readOnly value={url} onFocus={(e) => e.target.select()} />
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

  if (error) return <Mensaje tipo="error">{error}</Mensaje>
  if (!d) return <Cargando />
  return (
    <div className="detalle-apoderado">
      <div>
        <Link to=".." relative="path" className="enlace"><ArrowLeft size={18} aria-hidden="true" /> Cuentas de padres</Link>
        <h2>{d.nombre}</h2>
        <p>
          <Insignia tono={TONO_ESTADO[d.estado]}>{ESTADO[d.estado]}</Insignia>
          <Insignia tono={TONO_NOTIF[d.notificaciones]}>{NOTIFICACIONES[d.notificaciones]}</Insignia>
          {d.dispositivos > 0 && <span className="tenue"> en {plural(d.dispositivos, 'celular', 'celulares')}</span>}
        </p>
        <p className="tenue">
          Celular: {d.celular || '—'}{d.activado_en && ` · Cuenta activada: ${fechaHora(d.activado_en)}`}
        </p>
        {d.estado !== 'sin_cuenta' && <button className="boton secundario chico" onClick={cerrarSesiones}>Cerrar sus sesiones</button>}
      </div>
      <section>
        <h3>Avisos</h3>
        <Tabla etiqueta="Avisos" filas={d.avisos} clave={(a) => a.creado_en + a.cuerpo}
               vacio={{ icono: Bell, titulo: 'Sin avisos', texto: 'Aún no hay avisos para este apoderado.' }}
               columnas={[
                 { id: 'aviso', titulo: 'Aviso', celda: (a) => <><b className="aviso-titulo">{a.titulo}</b> {a.cuerpo}</> },
                 { id: 'fecha', titulo: 'Fecha', nowrap: true, celda: (a) => fechaHora(a.creado_en) },
                 { id: 'estado', titulo: 'Estado', celda: (a) => <Insignia tono={TONO_ENTREGA[a.estado]}>{ENTREGA[a.estado]}</Insignia> },
               ]} />
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
        <Tabla etiqueta="Enlaces enviados" filas={d.invitaciones} clave={(i) => i.creado_en}
               vacio={{ icono: Link2, titulo: 'Ningún enlace', texto: 'Aún no se le envió un enlace de activación.' }}
               columnas={[
                 { id: 'creado', titulo: 'Creado', nowrap: true, celda: (i) => fechaHora(i.creado_en) },
                 { id: 'por', titulo: 'Por', vacio: (i) => !i.creado_por, celda: (i) => i.creado_por || '—' },
                 { id: 'estado', titulo: 'Estado', celda: (i) => (
                   <><Insignia tono={TONO_ENLACE[i.estado]}>{ENLACE[i.estado]}</Insignia>
                     {i.motivo_anulacion && <span className="segunda-linea">{i.motivo_anulacion}</span>}</>) },
                 { id: 'intentos', titulo: 'Intentos', numero: true, celda: (i) => i.intentos },
               ]} />
      </section>
      <section>
        <h3>Cambios de datos</h3>
        <Tabla etiqueta="Cambios de datos" filas={d.cambios} clave={(c) => c.creado_en + c.campo}
               vacio={{ icono: History, titulo: 'Sin cambios', texto: 'Sus datos no cambiaron desde que se cargaron.' }}
               columnas={[
                 { id: 'dato', titulo: 'Dato', celda: (c) => c.campo },
                 { id: 'fecha', titulo: 'Fecha', nowrap: true, celda: (c) => fechaHora(c.creado_en) },
                 { id: 'antes', titulo: 'Antes', vacio: (c) => !c.antes, celda: (c) => c.antes || '—' },
                 { id: 'despues', titulo: 'Después', celda: (c) => c.despues },
                 { id: 'por', titulo: 'Por', celda: (c) => <>{c.por || '—'} <span className="tenue">({ORIGEN[c.origen]})</span></> },
               ]} />
      </section>
    </div>
  )
}
