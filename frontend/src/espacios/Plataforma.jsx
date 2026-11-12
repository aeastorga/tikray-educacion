import { useCallback, useEffect, useState } from 'react'
import { api, guardarToken, leerToken } from '../api.js'
import { School } from 'lucide-react'
import { Encabezado, Insignia, MenuAcciones, plural, Tabla, useConfirmar, Ventana } from './comun/index.js'
import { CamposPerfil, FormFacturacion } from './Configuracion.jsx'
import './configuracion.css'

// Panel de Tikray Labs (plataforma.<dominio>). Usa su propio token: el de un
// colegio no sirve aquí y este no sirve en ningún colegio.
export default function Plataforma() {
  const [sesion, setSesion] = useState(Boolean(leerToken()))
  useEffect(() => {
    document.title = 'Tikray Labs · Plataforma'
    const cerrar = () => setSesion(false)
    window.addEventListener('sesion-cerrada', cerrar)
    return () => window.removeEventListener('sesion-cerrada', cerrar)
  }, [])
  return sesion ? <Colegios salir={() => { guardarToken(null); setSesion(false) }} /> : <Ingreso entrar={() => setSesion(true)} />
}

function Ingreso({ entrar }) {
  const [correo, setCorreo] = useState('')
  const [clave, setClave] = useState('')
  const [error, setError] = useState(null)

  async function enviar(e) {
    e.preventDefault()
    try {
      const r = await api('/plataforma/auth/ingreso', { metodo: 'POST', datos: { correo, clave } })
      guardarToken(r.token)
      entrar()
    } catch (err) { setError(err.message) }
  }

  return (
    <main className="centro">
      <form className="tarjeta" onSubmit={enviar}>
        <h1>Tikray Labs</h1>
        <label>Correo<input type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} autoComplete="username" required /></label>
        <label>Clave<input type="password" value={clave} onChange={(e) => setClave(e.target.value)} autoComplete="current-password" required /></label>
        {error && <p className="error">{error}</p>}
        <button className="boton">Ingresar</button>
      </form>
    </main>
  )
}

const VACIO = {
  nombre: '', subdominio: '', estado: 'activo', vence_en: '',
  tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '',
}
const ESTADOS = { prueba: 'Prueba', activo: 'Activo', suspendido: 'Suspendido' }

function Colegios({ salir }) {
  const { confirmar } = useConfirmar()
  const [lista, setLista] = useState([])
  const [nuevo, setNuevo] = useState(VACIO)
  const [creado, setCreado] = useState(null)
  const [demoLista, setDemoLista] = useState(null)
  const [error, setError] = useState(null)
  const [editando, setEditando] = useState(null)
  const [activando, setActivando] = useState(null)
  const [facturando, setFacturando] = useState(null)
  const [activado, setActivado] = useState(null)

  const cargar = useCallback(() => api('/plataforma/colegios').then(setLista).catch(() => {}), [])
  useEffect(() => { cargar() }, [cargar])

  const campo = (k) => ({ value: nuevo[k], onChange: (e) => setNuevo({ ...nuevo, [k]: e.target.value }) })

  async function crear(e) {
    e.preventDefault()
    setError(null)
    try {
      const r = await api('/plataforma/colegios', {
        metodo: 'POST',
        datos: {
          nombre: nuevo.nombre, subdominio: nuevo.subdominio.toLowerCase(),
          estado: nuevo.estado, vence_en: nuevo.vence_en || null,
          administrador: {
            tipo_documento: nuevo.tipo_documento, numero_documento: nuevo.numero_documento,
            nombres: nuevo.nombres, apellidos: nuevo.apellidos,
          },
        },
      })
      setCreado(r)
      setNuevo(VACIO)
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function demo(c) {
    const texto = c ? `¿Reiniciar ${c.nombre}? Se borra todo lo que se cargó y vuelven los datos ficticios.`
      : '¿Crear el colegio demo (subdominio "demo") con datos ficticios?'
    if (!await confirmar({ titulo: c ? 'Reiniciar demo' : 'Crear colegio demo', texto, accion: c ? 'Reiniciar' : 'Crear', peligro: !!c })) return
    setError(null)
    try {
      const r = await api(c ? `/plataforma/colegios/${c.id}/reiniciar-demo` : '/plataforma/demo', { metodo: 'POST', datos: c ? undefined : {} })
      setDemoLista(r)
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function cambiar(c, datos) {
    if (datos.estado === 'suspendido' && !await confirmar({ titulo: 'Suspender colegio', texto: `Nadie de ${c.nombre} podrá entrar.`, accion: 'Suspender', peligro: true })) return
    setError(null)
    try { await api(`/plataforma/colegios/${c.id}`, { metodo: 'PATCH', datos }) } catch (err) { setError(err.message) }
    cargar()
  }

  const base = window.location.host.replace(/^plataforma\./, '')

  return (
    <div className="panel">
      <header className="cabecera">
        <h1>Tikray Labs · Colegios</h1>
        <div className="usuario"><button className="enlace" onClick={salir}>Salir</button></div>
      </header>
      <main className="contenido">
        {creado && (
          <div className="aviso">
            Colegio <b>{creado.colegio.nombre}</b> creado. Administrador: usuario <code>{creado.administrador_usuario}</code>,
            clave temporal <code>{creado.administrador_clave_temporal}</code>
            <br /><span className="tenue">Se muestra una sola vez.</span>
            <button className="enlace" onClick={() => setCreado(null)}>Cerrar</button>
          </div>
        )}
        {demoLista && (
          <div className="aviso">
            Demo lista: {plural(demoLista.alumnos, 'alumno', 'alumnos')}, {plural(demoLista.apoderados, 'apoderado', 'apoderados')}, {demoLista.personal} del personal.
            Clave del personal <code>{demoLista.credenciales.administrador.clave}</code>: administrador <code>{demoLista.credenciales.administrador.usuario}</code>,
            portería <code>{demoLista.credenciales.porteria.usuario}</code>, docente <code>{demoLista.credenciales.docente.usuario}</code>.
            Familia <code>{demoLista.credenciales.familia.documento}</code> con PIN <code>{demoLista.credenciales.familia.pin}</code>.
            <button className="enlace" onClick={() => setDemoLista(null)}>Cerrar</button>
          </div>
        )}
        {activado && (
          <div className="aviso">
            <b>{activado.colegio.nombre}</b> ya está activo.
            {Object.keys(activado.borrados).length > 0 && <> Se borraron los datos de ejemplo
              ({plural(activado.borrados.alumno || 0, 'alumno', 'alumnos')}, {plural(activado.borrados.apoderado || 0, 'apoderado', 'apoderados')}).</>}
            <button className="enlace" onClick={() => setActivado(null)}>Cerrar</button>
          </div>
        )}
        <Encabezado titulo="Colegios" descripcion="Estado, vencimiento y módulos contratados de cada colegio." />
        <Tabla etiqueta="Colegios" filas={lista}
               vacio={{ icono: School, titulo: 'Todavía no hay colegios', texto: 'Crea el primero con el formulario de abajo.' }}
               columnas={[
                 { id: 'colegio', titulo: 'Colegio', ancho: '24%', celda: (c) => (
                   <>
                     <b>{c.nombre}</b>
                     <span className="segunda-linea">
                       <a href={`//${c.subdominio}.${base}`} target="_blank" rel="noreferrer">{c.subdominio}.{base}</a>
                       {c.dominio_propio && <> · {c.dominio_propio}</>}
                     </span>
                   </>
                 ) },
                 { id: 'estado', titulo: 'Estado', celda: (c) => (
                   <>
                     <select value={c.estado} aria-label={`Estado de ${c.nombre}`} onChange={(e) => cambiar(c, { estado: e.target.value })}>
                       {Object.entries(ESTADOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                     </select>
                     {!c.disponible && c.estado !== 'suspendido' && <> <Insignia tono="falta">Vencido</Insignia></>}
                   </>
                 ) },
                 { id: 'vence', titulo: 'Vence', celda: (c) => (
                   <input type="date" value={c.vence_en || ''} aria-label={`Vencimiento de ${c.nombre}`}
                          onChange={(e) => cambiar(c, { vence_en: e.target.value || null })} />
                 ) },
                 { id: 'modulos', titulo: 'Módulos', ocultarEnCelular: true,
                   celda: (c) => <span className="tenue">{c.modulos.filter((m) => m.contratado).map((m) => m.nombre).join(', ') || 'Ninguno'}</span> },
                 { id: 'acciones', acciones: true, celda: (c) => (
                   <MenuAcciones etiqueta={c.nombre} principal={{ texto: 'Perfil y módulos', alHacer: () => setEditando(c) }}
                                 opciones={[
                                   { texto: 'Comprobantes electrónicos', alHacer: () => setFacturando(c) },
                                   c.estado === 'prueba' && !c.es_demo && { texto: 'Activar colegio', alHacer: () => setActivando(c) },
                                   c.es_demo && { texto: 'Reiniciar demo', alHacer: () => demo(c) },
                                 ].filter(Boolean)} />
                 ) },
               ]} />
        {editando && <EditarColegio colegio={editando} cerrar={() => setEditando(null)} alGuardar={cargar} />}
        {facturando && (
          <Dialogo titulo={`Comprobantes electrónicos de ${facturando.nombre}`} cerrar={() => setFacturando(null)}>
            <div className="configuracion">
              <FormFacturacion url={`/plataforma/colegios/${facturando.id}/facturacion`} />
              <div className="acciones">
                <button type="button" className="boton secundario" onClick={() => setFacturando(null)}>Cerrar</button>
              </div>
            </div>
          </Dialogo>
        )}
        {activando && <ActivarColegio colegio={activando} cerrar={() => setActivando(null)}
                                      alActivar={(r) => { setActivando(null); setActivado(r); cargar() }} />}
        {!lista.some((c) => c.es_demo) && (
          <p><button className="boton secundario" onClick={() => demo(null)}>Crear colegio demo con datos ficticios</button></p>
        )}
        <h2>Nuevo colegio</h2>
        <form className="fila-form" onSubmit={crear}>
          <input placeholder="Nombre del colegio" required {...campo('nombre')} />
          <input placeholder="subdominio" required pattern="[a-z0-9]([a-z0-9\-]*[a-z0-9])?" {...campo('subdominio')} />
          <select {...campo('estado')}>
            {Object.entries(ESTADOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label>Vence
            <input type="date" required={nuevo.estado === 'prueba'} {...campo('vence_en')} />
          </label>
          <select {...campo('tipo_documento')}>
            <option value="DNI">DNI</option>
            <option value="CE">Carné de extranjería</option>
          </select>
          <input placeholder="Documento del administrador" required {...campo('numero_documento')} />
          <input placeholder="Nombres del administrador" required {...campo('nombres')} />
          <input placeholder="Apellidos del administrador" required {...campo('apellidos')} />
          <button className="boton">Crear</button>
          {error && <p className="error">{error}</p>}
        </form>
      </main>
    </div>
  )
}

// Las ventanas con formulario usan la misma ventana que confirmar y pedir motivo (espacios/comun/Dialogo.jsx).
function Dialogo({ titulo, cerrar, children }) {
  return <Ventana titulo={titulo} mostrarTitulo={false} ancha cerrar={cerrar}>{children}</Ventana>
}

function EditarColegio({ colegio, cerrar, alGuardar }) {
  const [perfil, setPerfil] = useState(colegio.perfil)
  const [contratados, setContratados] = useState(colegio.modulos.filter((m) => m.contratado).map((m) => m.clave))
  const [maximo, setMaximo] = useState(colegio.max_usuarios ?? '')
  const [error, setError] = useState(null)

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    try {
      await api(`/plataforma/colegios/${colegio.id}`, { metodo: 'PATCH', datos: { perfil, modulos_contratados: contratados, max_usuarios: maximo === '' ? null : Number(maximo) } })
      alGuardar()
      cerrar()
    } catch (err) { setError(err.message) }
  }

  return (
    <Dialogo titulo={`Perfil y módulos de ${colegio.nombre}`} cerrar={cerrar}>
      <form onSubmit={guardar} className="configuracion">
        <h2>{colegio.nombre}</h2>
        <CamposPerfil perfil={perfil} cambiar={setPerfil} />
        <fieldset className="gestion">
          <legend>Módulos contratados</legend>
          {colegio.modulos.map((m) => (
            <label key={m.clave} className="check">
              <input type="checkbox" checked={contratados.includes(m.clave)}
                     onChange={(e) => setContratados(e.target.checked ? [...contratados, m.clave] : contratados.filter((x) => x !== m.clave))} />
              {m.nombre}
            </label>
          ))}
        </fieldset>
        <p className="tenue sin-margen">El administrador prende o apaga solo lo contratado. Lo que se quita aquí se apaga para todo el colegio.</p>
        <label><span>Límite de usuarios del personal</span>
          <input type="number" min="1" step="1" inputMode="numeric" placeholder="Sin límite" value={maximo}
                 onChange={(e) => setMaximo(e.target.value)} />
        </label>
        <p className="tenue sin-margen">Cuentan los usuarios activos, incluido el administrador; los padres no. Vacío = sin límite. Si lo bajas de los activos, nadie se desactiva: solo no podrán agregar más.</p>
        {error && <p className="error">{error}</p>}
        <div className="acciones">
          <button className="boton">Guardar</button>
          <button type="button" className="boton secundario" onClick={cerrar}>Cancelar</button>
        </div>
      </form>
    </Dialogo>
  )
}

function ActivarColegio({ colegio, cerrar, alActivar }) {
  const [borrar, setBorrar] = useState(true)
  const [confirmar, setConfirmar] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const coincide = confirmar.trim().toLowerCase() === colegio.subdominio

  async function activar(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      alActivar(await api(`/plataforma/colegios/${colegio.id}/activar`, { metodo: 'POST', datos: { borrar_ejemplo: borrar, confirmar } }))
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  return (
    <Dialogo titulo={`Activar ${colegio.nombre}`} cerrar={cerrar}>
      <form onSubmit={activar} className="configuracion">
        <h2>Activar {colegio.nombre}</h2>
        <p className="sin-margen">Pasa de prueba a activo y deja de vencer.</p>
        <label className="check">
          <input type="checkbox" checked={borrar} onChange={(e) => setBorrar(e.target.checked)} />
          Borrar los datos de ejemplo
        </label>
        {borrar && (
          <div className="aviso">
            <p className="sin-margen"><b>Se borran:</b> alumnos, apoderados, marcaciones, cuaderno y avisos.</p>
            <p className="sin-margen"><b>Se conservan:</b> estructura, turnos, calendario, roles, personal, imagen y configuración.</p>
          </div>
        )}
        <label><span>Escribe <code>{colegio.subdominio}</code> para confirmar</span>
          <input value={confirmar} onChange={(e) => setConfirmar(e.target.value)} autoComplete="off" autoFocus
                 spellCheck={false} autoCapitalize="none" />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="acciones">
          <button className="boton" disabled={!coincide || enviando}>{enviando ? 'Activando…' : 'Activar colegio'}</button>
          <button type="button" className="boton secundario" onClick={cerrar}>Cancelar</button>
        </div>
      </form>
    </Dialogo>
  )
}
