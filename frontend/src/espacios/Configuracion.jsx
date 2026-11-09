// Configuración del colegio (administrador o quien tenga el permiso): imagen, perfil, módulos, avisos a los
// padres, plantillas de comunicados y categorías de incidencias. Más el historial de actividad y los
// comprobantes electrónicos (solo administrador; Tikray Labs usa el mismo formulario en su panel).
import { Award, History, Pencil, Plus, Trash2, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from '../api.js'
import { aplicarImagen } from '../App.jsx'
import { LIMA } from '../tema.js'
import { Encabezado, fechaHora as fechaHoraComun, Insignia, Paginacion, Tabla, usePaginado } from './comun/index.js'
import './configuracion.css'

const TIPOS_AVISO = [
  ['ingreso', 'Ingreso', 'Cuando el alumno marca su entrada a tiempo.'],
  ['tardanza', 'Tardanza', 'Cuando llega después de la tolerancia del turno.'],
  ['falta', 'Falta', 'Cuando no llegó a la hora de corte del turno.'],
  ['salida', 'Salida', 'Cuando marca su salida.'],
  ['cuaderno', 'Cuaderno de control', 'Comunicados, incidencias, citaciones y respuestas.'],
  ['cobro', 'Recordatorio de pago', 'Días antes del vencimiento y el día que vence, solo al responsable de pago.'],
]

export default function Configuracion({ editar, administrador, colegio, setColegio, recargarYo }) {
  return (
    <section className="configuracion">
      <h2>Configuración</h2>
      <nav className="subpestanas">
        <NavLink to="/panel/configuracion" end>Imagen</NavLink>
        <NavLink to="/panel/configuracion/perfil">Perfil</NavLink>
        <NavLink to="/panel/configuracion/modulos">Módulos</NavLink>
        <NavLink to="/panel/configuracion/avisos">Avisos</NavLink>
        <NavLink to="/panel/configuracion/plantillas">Plantillas</NavLink>
        <NavLink to="/panel/configuracion/categorias">Categorías</NavLink>
        {administrador && <NavLink to="/panel/configuracion/comprobantes">Comprobantes</NavLink>}
      </nav>
      <Routes>
        <Route index element={<Imagen editar={editar} colegio={colegio} setColegio={setColegio} />} />
        <Route path="perfil" element={<Perfil editar={editar} />} />
        <Route path="modulos" element={<Modulos editar={editar} alCambiar={recargarYo} />} />
        <Route path="avisos" element={<Avisos editar={editar} />} />
        <Route path="plantillas" element={<Plantillas editar={editar} />} />
        <Route path="categorias" element={<Categorias editar={editar} />} />
        {administrador && <Route path="comprobantes" element={(
          <div className="tarjeta-panel"><FormFacturacion url="/api/configuracion/facturacion" /></div>)} />}
      </Routes>
    </section>
  )
}

function Estado({ mensaje }) {
  if (!mensaje) return null
  return <p className={mensaje.error ? 'error' : 'tenue'} role="status">{mensaje.texto}</p>
}

// Envuelve una llamada: muestra "Guardado" o el error del servidor.
function useGuardar() {
  const [mensaje, setMensaje] = useState(null)
  const guardar = useCallback(async (fn, ok = 'Cambios guardados') => {
    setMensaje(null)
    try { const r = await fn(); setMensaje({ texto: ok }); return r }
    catch (err) { setMensaje({ texto: err.message, error: true }); return null }
  }, [])
  return [mensaje, guardar, setMensaje]
}

// --- Imagen ----------------------------------------------------------------------------------

function Imagen({ editar, colegio, setColegio }) {
  const [colores, setColores] = useState({ color_primario: colegio.color_primario, color_secundario: colegio.color_secundario })
  const [mensaje, guardar] = useGuardar()

  function aplicar(c) { if (c) { setColegio(c); aplicarImagen(c) } }

  async function guardarColores(e) {
    e.preventDefault()
    aplicar(await guardar(() => api('/api/colegio/imagen', { metodo: 'PUT', datos: colores }), 'Colores guardados'))
  }

  async function cambiarMenu(claro) {
    aplicar(await guardar(() => api('/api/colegio/imagen', { metodo: 'PUT', datos: {
      color_primario: colegio.color_primario, color_secundario: colegio.color_secundario, menu_claro: claro } }),
    claro ? 'Menú claro activado' : 'Menú oscuro activado'))
  }

  async function subirLogo(e) {
    const archivo = e.target.files[0]
    if (!archivo) return
    aplicar(await guardar(() => api('/api/colegio/logo', { metodo: 'PUT', archivo }), 'Logo actualizado'))
    e.target.value = ''
  }

  async function quitarLogo() {
    aplicar(await guardar(() => api('/api/colegio/logo', { metodo: 'DELETE' }), 'Logo quitado'))
  }

  return (
    <>
      <div className="tarjeta-panel">
        <h2>Imagen del colegio</h2>
        <p className="tenue">El color principal es el acento de todo el sistema: botones, menú, la tarjeta en vivo de las familias.
          Si no se lee bien con texto blanco, se oscurece solo en los botones.</p>
        <form onSubmit={guardarColores} className="fila-form">
          <label>Color principal
            <input type="color" value={colores.color_primario} disabled={!editar}
                   onChange={(e) => setColores({ ...colores, color_primario: e.target.value })} />
          </label>
          <label>Color secundario
            <input type="color" value={colores.color_secundario} disabled={!editar}
                   onChange={(e) => setColores({ ...colores, color_secundario: e.target.value })} />
          </label>
          {editar && <button className="boton">Guardar colores</button>}
        </form>
        {editar && (
          <div className="fila-form">
            <label>Logo (PNG, JPG o WEBP, hasta 200 KB)
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={subirLogo} />
            </label>
            {colegio.logo_url && <button className="enlace" onClick={quitarLogo}>Quitar logo</button>}
          </div>
        )}
      </div>
      <fieldset className="tarjeta-panel elegir-menu" disabled={!editar}>
        <legend><h2>Menú lateral</h2></legend>
        <p className="tenue">Cómo ve el menú todo el personal del colegio.</p>
        <div className="opciones-menu">
          {[[false, 'Oscuro'], [true, 'Claro']].map(([claro, texto]) => (
            <label key={texto} className={`opcion-menu ${claro ? 'claro' : 'oscuro'}`}>
              <input type="radio" name="menu" checked={Boolean(colegio.menu_claro) === claro} onChange={() => cambiarMenu(claro)} />
              <span className="muestra-menu" aria-hidden="true"><i /><i /><i /></span>
              {texto}
            </label>
          ))}
        </div>
      </fieldset>
      <Estado mensaje={mensaje} />
    </>
  )
}

// --- Perfil ----------------------------------------------------------------------------------

export function CamposPerfil({ perfil, cambiar, deshabilitado }) {
  const campo = (k) => ({ value: perfil[k] ?? '', disabled: deshabilitado, onChange: (e) => cambiar({ ...perfil, [k]: e.target.value }) })
  return (
    <div className="rejilla-perfil">
      <fieldset className="gestion" disabled={deshabilitado}>
        <legend>Tipo de gestión</legend>
        {[['particular', 'Particular'], ['estatal', 'Estatal']].map(([v, t]) => (
          <label key={v} className="check">
            <input type="radio" name="tipo_gestion" checked={perfil.tipo_gestion === v}
                   onChange={() => cambiar({ ...perfil, tipo_gestion: v })} />{t}
          </label>
        ))}
      </fieldset>
      <label>UGEL<input {...campo('ugel')} maxLength={120} placeholder="UGEL 03 Breña" /></label>
      <label>Código modular<input {...campo('codigo_modular')} inputMode="numeric" pattern="\d{7}" maxLength={7}
                                  title="7 dígitos" placeholder="0123456" /></label>
      <label className="ancho">Dirección<input {...campo('direccion')} maxLength={250} autoComplete="street-address" /></label>
      <label>Teléfono de contacto<input {...campo('telefono')} type="tel" maxLength={20} autoComplete="tel" /></label>
      <label>Correo de contacto<input {...campo('correo_contacto')} type="email" maxLength={254} autoComplete="email" /></label>
    </div>
  )
}

function Perfil({ editar }) {
  const [perfil, setPerfil] = useState(null)
  const [mensaje, guardar] = useGuardar()
  useEffect(() => { api('/api/configuracion/perfil').then(setPerfil) }, [])
  if (!perfil) return <p className="tenue">Cargando…</p>

  async function enviar(e) {
    e.preventDefault()
    const r = await guardar(() => api('/api/configuracion/perfil', { metodo: 'PUT', datos: perfil }), 'Perfil guardado')
    if (r) setPerfil(r)
  }

  return (
    <form className="tarjeta-panel" onSubmit={enviar}>
      <h2>Perfil del colegio</h2>
      <p className="tenue">Datos oficiales del colegio. El tipo de gestión define, más adelante, cómo se llevan la caja y los gastos.</p>
      <CamposPerfil perfil={perfil} cambiar={setPerfil} deshabilitado={!editar} />
      {editar && <div className="acciones"><button className="boton">Guardar perfil</button></div>}
      <Estado mensaje={mensaje} />
    </form>
  )
}

// --- Comprobantes electrónicos (administrador y Tikray Labs) --------------------------------------------

export function FormFacturacion({ url, alGuardar }) {
  const [cfg, setCfg] = useState(null)
  const [token, setToken] = useState('')
  const [mensaje, guardar] = useGuardar()
  useEffect(() => { api(url).then(setCfg).catch(() => setCfg(false)) }, [url])
  if (cfg === false) return <p className="error">No se pudo cargar la configuración.</p>
  if (!cfg) return <p className="tenue">Cargando…</p>
  const campo = (k) => ({ value: cfg[k] ?? '', onChange: (e) => setCfg({ ...cfg, [k]: e.target.value }) })

  async function enviar(e) {
    e.preventDefault()
    const datos = { emite: cfg.emite, ruc: cfg.ruc, razon_social: cfg.razon_social, serie_boleta: cfg.serie_boleta,
      serie_factura: cfg.serie_factura, proveedor: cfg.proveedor, token: token.trim() || null }
    const r = await guardar(() => api(url, { metodo: 'PUT', datos }), 'Comprobantes guardados')
    if (r) { setCfg(r); setToken(''); alGuardar?.() }
  }

  return (
    <form onSubmit={enviar} className="form-facturacion">
      <h2>Comprobantes electrónicos SUNAT</h2>
      <p className="tenue">Con la emisión apagada, o sin proveedor, el colegio sigue solo con el recibo interno.
        Al cobrar sale una boleta a nombre del responsable de pago, o una factura si el cajero la pide con RUC.</p>
      {!cfg.clave_configurada && (
        <p className="aviso" role="alert">Falta la clave de facturación en el servidor (FACTURACION_CLAVE): la emisión no se puede activar ni se puede guardar el token. Pídela a Tikray Labs.</p>
      )}
      <label className="check">
        <input type="checkbox" checked={cfg.emite} onChange={(e) => setCfg({ ...cfg, emite: e.target.checked })} />
        Emite comprobantes electrónicos
      </label>
      <div className="rejilla-perfil">
        <label>RUC<input {...campo('ruc')} inputMode="numeric" pattern="\d{11}" maxLength={11} title="11 dígitos" /></label>
        <label className="ancho">Razón social<input {...campo('razon_social')} maxLength={200} /></label>
        <label>Serie de boleta<input {...campo('serie_boleta')} required pattern="[Bb][0-9A-Za-z]{3}" maxLength={4} title="B y tres letras o dígitos, por ejemplo B001" /></label>
        <label>Serie de factura<input {...campo('serie_factura')} required pattern="[Ff][0-9A-Za-z]{3}" maxLength={4} title="F y tres letras o dígitos, por ejemplo F001" /></label>
        <label>Proveedor
          <select {...campo('proveedor')}>
            {cfg.proveedores.map((p) => <option key={p.clave} value={p.clave}>{p.nombre}</option>)}
          </select>
        </label>
        <label>Token del proveedor
          <input type="password" autoComplete="new-password" maxLength={2000} value={token}
                 placeholder={cfg.token_configurado ? 'Configurado (escribe otro para cambiarlo)' : 'Sin configurar'}
                 onChange={(e) => setToken(e.target.value)} />
        </label>
      </div>
      <p className="tenue sin-margen">{cfg.token_configurado ? 'Token: configurado.' : 'Token: sin configurar.'} Se guarda cifrado y nunca se vuelve a mostrar.</p>
      <div className="acciones"><button className="boton">Guardar</button></div>
      <Estado mensaje={mensaje} />
    </form>
  )
}

// --- Módulos ---------------------------------------------------------------------------------

const DESCRIPCION_MODULO = {
  asistencia: 'Portería con QR, faltas automáticas, licencias y reportes.',
  cuaderno: 'Comunicados con firma, incidencias, citaciones, justificaciones y permisos de salida.',
  familias: 'Invitación, aprobación y bloqueo de las cuentas de los padres.',
  reuniones: 'Modo reunión: ficha y consentimiento con el QR del aula.',
}

function Modulos({ editar, alCambiar }) {
  const [modulos, setModulos] = useState(null)
  const [mensaje, guardar] = useGuardar()
  useEffect(() => { api('/api/configuracion/modulos').then(setModulos) }, [])
  if (!modulos) return <p className="tenue">Cargando…</p>

  async function cambiar(clave, activo) {
    const activos = modulos.filter((m) => (m.clave === clave ? activo : m.activo)).map((m) => m.clave)
    const r = await guardar(() => api('/api/configuracion/modulos', { metodo: 'PUT', datos: { activos } }),
      'Módulos guardados')
    if (r) { setModulos(r); alCambiar?.() }
  }

  return (
    <div className="tarjeta-panel">
      <h2>Módulos</h2>
      <p className="tenue">Un módulo apagado desaparece del menú de todo el personal y de la app de las familias.
        Solo se prenden los que el colegio tiene contratados.</p>
      <ul className="lista-interruptores">
        {modulos.map((m) => (
          <li key={m.clave}>
            <div>
              <b>{m.nombre}</b>
              <span className="tenue">{DESCRIPCION_MODULO[m.clave]}</span>
              {!m.contratado && <span className="chip no-contratado">No contratado: pídelo a Tikray Labs</span>}
            </div>
            <Interruptor etiqueta={m.nombre} activo={m.activo} deshabilitado={!editar || !m.contratado}
                         cambiar={(v) => cambiar(m.clave, v)} />
          </li>
        ))}
      </ul>
      <Estado mensaje={mensaje} />
    </div>
  )
}

export function Interruptor({ etiqueta, activo, cambiar, deshabilitado }) {
  return (
    <label className="interruptor">
      <input type="checkbox" role="switch" checked={activo} disabled={deshabilitado}
             onChange={(e) => cambiar(e.target.checked)} aria-label={etiqueta} />
      <span aria-hidden="true" />
      <span className="interruptor-texto">{activo ? 'Prendido' : 'Apagado'}</span>
    </label>
  )
}

// --- Avisos ----------------------------------------------------------------------------------

function Avisos({ editar }) {
  const [avisos, setAvisos] = useState(null)
  const [mensaje, guardar] = useGuardar()
  useEffect(() => { api('/api/configuracion/avisos').then(setAvisos) }, [])
  if (!avisos) return <p className="tenue">Cargando…</p>

  async function enviar(datos, ok) {
    const r = await guardar(() => api('/api/configuracion/avisos', { metodo: 'PUT', datos }), ok)
    if (r) setAvisos(r)
  }

  function cambiarTipo(t, v) { enviar({ ...avisos, tipos: { ...avisos.tipos, [t]: v } }, 'Avisos guardados') }

  function guardarSilencio(e) {
    e.preventDefault()
    const f = new FormData(e.target)
    enviar({ ...avisos, silencio_desde: f.get('desde'), silencio_hasta: f.get('hasta') }, 'Horario guardado')
  }

  return (
    <>
      <div className="tarjeta-panel">
        <h2>Qué avisos reciben los padres</h2>
        <p className="tenue">Notificaciones en el celular de cada apoderado con la app. Lo apagado no se envía.</p>
        <ul className="lista-interruptores">
          {TIPOS_AVISO.map(([t, nombre, ayuda]) => (
            <li key={t}>
              <div><b>{nombre}</b><span className="tenue">{ayuda}</span></div>
              <Interruptor etiqueta={nombre} activo={avisos.tipos[t]} deshabilitado={!editar} cambiar={(v) => cambiarTipo(t, v)} />
            </li>
          ))}
        </ul>
      </div>
      <form className="tarjeta-panel" onSubmit={guardarSilencio}>
        <h2>Horario sin molestar</h2>
        <p className="tenue">Lo del cuaderno que se escriba en este horario espera y sale cuando termina. Los avisos de
          asistencia (ingreso, tardanza, falta, salida) salen siempre. Hora de Lima.</p>
        <div className="fila-form">
          <label>Desde<input type="time" name="desde" defaultValue={avisos.silencio_desde} disabled={!editar} required /></label>
          <label>Hasta<input type="time" name="hasta" defaultValue={avisos.silencio_hasta} disabled={!editar} required /></label>
          {editar && <button className="boton">Guardar horario</button>}
        </div>
        <p className="tenue pequeno">Para no usar horario sin molestar, pon la misma hora en ambos.</p>
      </form>
      <Estado mensaje={mensaje} />
    </>
  )
}

// --- Plantillas ------------------------------------------------------------------------------

const PLANTILLA_VACIA = { nombre: '', titulo: '', cuerpo: '' }

function Plantillas({ editar }) {
  const [lista, setLista] = useState(null)
  const [form, setForm] = useState(null) // null: cerrado; {id?}: nueva o editando
  const [mensaje, guardar] = useGuardar()
  const cargar = useCallback(() => api('/api/configuracion/plantillas').then(setLista), [])
  useEffect(() => { cargar() }, [cargar])
  if (!lista) return <p className="tenue">Cargando…</p>

  async function enviar(e) {
    e.preventDefault()
    const { id, ...datos } = form
    const r = await guardar(() => api(`/api/configuracion/plantillas${id ? `/${id}` : ''}`,
      { metodo: id ? 'PUT' : 'POST', datos }), id ? 'Plantilla guardada' : 'Plantilla creada')
    if (r) { setForm(null); cargar() }
  }

  async function borrar(p) {
    if (!window.confirm(`¿Borrar la plantilla «${p.nombre}»?`)) return
    await guardar(() => api(`/api/configuracion/plantillas/${p.id}`, { metodo: 'DELETE' }), 'Plantilla borrada')
    cargar()
  }

  return (
    <div className="tarjeta-panel">
      <div className="cabecera-seccion">
        <div>
          <h2>Plantillas de comunicados</h2>
          <p className="tenue">Asunto y texto listos para elegir al escribir un comunicado en el cuaderno.</p>
        </div>
        {editar && !form && <button className="boton" onClick={() => setForm(PLANTILLA_VACIA)}><Plus aria-hidden="true" />Nueva plantilla</button>}
      </div>
      {form && (
        <form className="form-plantilla" onSubmit={enviar}>
          <label>Nombre de la plantilla<input value={form.nombre} maxLength={80} required autoFocus
                                              onChange={(e) => setForm({ ...form, nombre: e.target.value })} /></label>
          <label>Asunto<input value={form.titulo} maxLength={200} required
                              onChange={(e) => setForm({ ...form, titulo: e.target.value })} /></label>
          <label>Texto<textarea rows={5} value={form.cuerpo} maxLength={10000}
                                onChange={(e) => setForm({ ...form, cuerpo: e.target.value })} /></label>
          <div className="acciones">
            <button className="boton">{form.id ? 'Guardar cambios' : 'Crear plantilla'}</button>
            <button type="button" className="boton secundario" onClick={() => setForm(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {lista.length === 0 ? <p className="tenue">Aún no hay plantillas.</p> : (
        <ul className="lista-plantillas">
          {lista.map((p) => (
            <li key={p.id}>
              <div>
                <b>{p.nombre}</b>
                <span>{p.titulo}</span>
                {p.cuerpo && <span className="tenue recorte">{p.cuerpo}</span>}
              </div>
              {editar && (
                <div className="acciones">
                  <button className="boton-icono" aria-label={`Editar ${p.nombre}`} onClick={() => setForm(p)}><Pencil aria-hidden="true" /></button>
                  <button className="boton-icono" aria-label={`Borrar ${p.nombre}`} onClick={() => borrar(p)}><Trash2 aria-hidden="true" /></button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Estado mensaje={mensaje} />
    </div>
  )
}

// --- Categorías de incidencias ---------------------------------------------------------------

function Categorias({ editar }) {
  const [lista, setLista] = useState(null)
  const [editando, setEditando] = useState(null)
  const [mensaje, guardar] = useGuardar()
  const cargar = useCallback(() => api('/api/configuracion/categorias').then(setLista), [])
  useEffect(() => { cargar() }, [cargar])
  if (!lista) return <p className="tenue">Cargando…</p>

  async function crear(e, tipo) {
    e.preventDefault()
    const input = e.target.elements.nombre
    const r = await guardar(() => api('/api/configuracion/categorias', { metodo: 'POST', datos: { nombre: input.value, tipo } }),
      'Categoría creada')
    if (r) { input.value = ''; cargar() }
  }

  async function actualizar(c, cambios, ok = 'Categoría guardada') {
    const r = await guardar(() => api(`/api/configuracion/categorias/${c.id}`, { metodo: 'PUT', datos: { ...c, ...cambios } }), ok)
    if (r) { setEditando(null); cargar() }
  }

  async function borrar(c) {
    if (!window.confirm(`¿Borrar la categoría «${c.nombre}»?`)) return
    await guardar(() => api(`/api/configuracion/categorias/${c.id}`, { metodo: 'DELETE' }), 'Categoría borrada')
    cargar()
  }

  const grupos = [
    ['merito', 'Méritos', 'La familia los ve resaltados en verde.', Award],
    ['mejora', 'A mejorar', 'Lo que hay que trabajar con el alumno.', TrendingUp],
  ]
  return (
    <>
      <p className="tenue sin-margen">Al registrar una incidencia se elige una de estas categorías. Una categoría que ya
        se usó no se borra: se desactiva y deja de aparecer al escribir.</p>
      <div className="grupos-categorias">
        {grupos.map(([tipo, titulo, ayuda, Icono]) => (
          <div key={tipo} className={`tarjeta-panel categorias ${tipo}`}>
            <h2 className="icono-texto"><Icono aria-hidden="true" />{titulo}</h2>
            <p className="tenue">{ayuda}</p>
            <ul className="lista-categorias">
              {lista.filter((c) => c.tipo === tipo).map((c) => (
                <li key={c.id} className={c.activa ? '' : 'inactiva'}>
                  {editando?.id === c.id ? (
                    <form className="fila-form sin-margen" onSubmit={(e) => { e.preventDefault(); actualizar(c, { nombre: editando.nombre }) }}>
                      <input value={editando.nombre} maxLength={60} required autoFocus aria-label="Nombre de la categoría"
                             onChange={(e) => setEditando({ ...editando, nombre: e.target.value })} />
                      <button className="boton">Guardar</button>
                      <button type="button" className="enlace" onClick={() => setEditando(null)}>Cancelar</button>
                    </form>
                  ) : (
                    <>
                      <span className="nombre-categoria">
                        {c.nombre}
                        {!c.activa && <span className="chip">Desactivada</span>}
                        {c.usos > 0 && <span className="tenue pequeno">{c.usos} {c.usos === 1 ? 'uso' : 'usos'}</span>}
                      </span>
                      {editar && (
                        <span className="acciones">
                          <button className="boton-icono" aria-label={`Renombrar ${c.nombre}`} onClick={() => setEditando(c)}><Pencil aria-hidden="true" /></button>
                          {c.usos > 0
                            ? <button className="enlace" onClick={() => actualizar(c, { activa: !c.activa }, c.activa ? 'Categoría desactivada' : 'Categoría activada')}>
                                {c.activa ? 'Desactivar' : 'Activar'}</button>
                            : <button className="boton-icono" aria-label={`Borrar ${c.nombre}`} onClick={() => borrar(c)}><Trash2 aria-hidden="true" /></button>}
                        </span>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
            {editar && (
              <form className="fila-form" onSubmit={(e) => crear(e, tipo)}>
                <input name="nombre" maxLength={60} required placeholder="Nueva categoría" aria-label={`Nueva categoría de ${titulo.toLowerCase()}`} />
                <button className="boton secundario"><Plus aria-hidden="true" />Agregar</button>
              </form>
            )}
          </div>
        ))}
      </div>
      <Estado mensaje={mensaje} />
    </>
  )
}

// --- Historial (solo el administrador) ------------------------------------------------------------

const ACCION = { crear: 'Creó', editar: 'Editó', anular: 'Anuló' }

const TONO_ACCION = { crear: 'bien', editar: 'info', anular: 'falta' }

export function Historial() {
  const [filtros, setFiltros] = useState({ usuario_id: '', modulo: '', desde: '', hasta: '' })
  const { datos, error, cargando, paginacion } = usePaginado('/api/configuracion/historial', filtros, { demora: 0 })

  function filtrar(k, v) { setFiltros({ ...filtros, [k]: v }) }
  const hayFiltros = Object.values(filtros).some(Boolean)

  return (
    <section className="historial">
      <Encabezado titulo="Historial de actividad"
                  descripcion="Quién hizo qué en el sistema. Nunca guarda claves, PIN, motivos de licencia ni el texto de las justificaciones." />
      <div className="filtros-historial">
        <label>Persona
          <select value={filtros.usuario_id} onChange={(e) => filtrar('usuario_id', e.target.value)}>
            <option value="">Todas</option>
            {datos?.personas.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
          </select>
        </label>
        <label>Módulo
          <select value={filtros.modulo} onChange={(e) => filtrar('modulo', e.target.value)}>
            <option value="">Todos</option>
            {datos?.modulos.map((m) => <option key={m.clave} value={m.clave}>{m.nombre}</option>)}
          </select>
        </label>
        <label>Desde<input type="date" value={filtros.desde} onChange={(e) => filtrar('desde', e.target.value)} /></label>
        <label>Hasta<input type="date" value={filtros.hasta} onChange={(e) => filtrar('hasta', e.target.value)} /></label>
        {hayFiltros && <button className="enlace" onClick={() => setFiltros({ usuario_id: '', modulo: '', desde: '', hasta: '' })}>Quitar filtros</button>}
      </div>
      {error && <p className="error">{error}</p>}
      <Tabla etiqueta="Historial de actividad" cargando={cargando} filas={datos?.items}
             vacio={{ icono: History, titulo: hayFiltros ? 'Nada con esos filtros' : 'Aún no hay actividad registrada',
                      texto: hayFiltros ? 'Prueba con otra persona, módulo o fechas.' : null }}
             columnas={[
               { id: 'resumen', titulo: 'Qué pasó', ancho: '42%', celda: (r) => r.resumen },
               { id: 'accion', titulo: 'Acción', celda: (r) => <Insignia tono={TONO_ACCION[r.accion] || 'neutro'}>{ACCION[r.accion] || r.accion}</Insignia> },
               { id: 'quien', titulo: 'Quién', celda: (r) => <>{r.quien}<span className="segunda-linea">{r.modulo_nombre}</span></> },
               { id: 'fecha', titulo: 'Fecha', nowrap: true, celda: (r) => <time dateTime={r.creado_en} className="tenue">{fechaHoraComun(r.creado_en)}</time> },
             ]} />
      {paginacion && <Paginacion {...paginacion} />}
    </section>
  )
}
