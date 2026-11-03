import { useCallback, useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { api, descargar, ErrorApi, guardarToken, leerToken } from '../api.js'
import { aplicarImagen } from '../App.jsx'
import { borrarPadron } from '../porteria/almacen.js'
import Asistencia from './Asistencia.jsx'
import Cabecera from './Cabecera.jsx'
import CambiarClave from './CambiarClave.jsx'
import CuentasPadres from './CuentasPadres.jsx'
import Padron from './Padron.jsx'

const NIVEL = { ver: 1, editar: 2 }
const puede = (yo, modulo, nivel = 'ver') => (NIVEL[yo.permisos[modulo]] || 0) >= NIVEL[nivel]
const CLAVE_YO = 'tikray.yo'

// Sin internet (portería) se usa la última sesión conocida; el servidor sigue validando el token al enviar.
function yoGuardado() {
  try { return JSON.parse(localStorage.getItem(CLAVE_YO)) } catch { return null }
}

export default function PanelColegio({ colegio, setColegio }) {
  const navegar = useNavigate()
  const [yo, setYo] = useState(null)

  const cargar = useCallback(() => api('/api/auth/yo')
    .then((y) => { setYo(y); try { localStorage.setItem(CLAVE_YO, JSON.stringify(y)) } catch { /* modo privado */ } })
    .catch((e) => { if (!(e instanceof ErrorApi)) setYo((actual) => actual || yoGuardado()) }), [])
  useEffect(() => { if (leerToken()) cargar() }, [cargar])
  useEffect(() => {
    const salir = () => navegar('/personal', { replace: true })
    window.addEventListener('sesion-cerrada', salir)
    return () => window.removeEventListener('sesion-cerrada', salir)
  }, [navegar])

  if (!leerToken()) return <Navigate to="/personal" replace />
  if (!yo) return <main className="centro"><p className="tenue">Cargando…</p></main>
  if (yo.debe_cambiar_clave) {
    return <main className="centro"><CambiarClave obligatorio alTerminar={cargar} /></main>
  }

  function salir() {
    guardarToken(null)
    try { localStorage.removeItem(CLAVE_YO) } catch { /* modo privado */ }
    borrarPadron()
    navegar('/', { replace: true })
  }

  return (
    <div className="panel">
      <Cabecera colegio={colegio}>
        <div className="usuario">
          <span>{yo.nombres} · {yo.rol}</span>
          <button className="enlace" onClick={salir}>Salir</button>
        </div>
      </Cabecera>
      <nav className="pestanas">
        <NavLink to="/panel" end>Inicio</NavLink>
        {puede(yo, 'asistencia') && <NavLink to="/panel/asistencia">Asistencia</NavLink>}
        {puede(yo, 'padron') && <NavLink to="/panel/padron">Padrón</NavLink>}
        {puede(yo, 'familias') && <NavLink to="/panel/familias">Cuentas de padres</NavLink>}
        {puede(yo, 'personal') && <NavLink to="/panel/personal">Personal</NavLink>}
        {puede(yo, 'roles') && <NavLink to="/panel/roles">Roles</NavLink>}
        {puede(yo, 'configuracion') && <NavLink to="/panel/imagen">Imagen del colegio</NavLink>}
        <NavLink to="/panel/clave">Mi clave</NavLink>
      </nav>
      <main className="contenido">
        <Routes>
          <Route index element={<p>Bienvenido, {yo.nombres}.</p>} />
          <Route path="asistencia/*" element={<Asistencia yo={yo} marcar={puede(yo, 'asistencia', 'editar')}
            licencias={puede(yo, 'personal', 'editar')} reglas={puede(yo, 'configuracion', 'editar')} />} />
          <Route path="padron/*" element={<Padron editar={puede(yo, 'padron', 'editar')} />} />
          <Route path="familias/*" element={<CuentasPadres colegio={colegio} editar={puede(yo, 'familias', 'editar')}
            reglas={puede(yo, 'configuracion', 'editar')} />} />
          <Route path="personal" element={<Personal yo={yo} />} />
          <Route path="roles" element={<Roles yo={yo} />} />
          <Route path="imagen" element={<Imagen yo={yo} colegio={colegio} setColegio={setColegio} />} />
          <Route path="clave" element={<CambiarClave alTerminar={() => navegar('/panel')} />} />
        </Routes>
      </main>
    </div>
  )
}

function Personal({ yo }) {
  const [lista, setLista] = useState([])
  const [roles, setRoles] = useState([])
  const [turnos, setTurnos] = useState([])
  const vacio = { tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '', rol_id: '' }
  const [nuevo, setNuevo] = useState(vacio)
  const [clave, setClave] = useState(null)
  const [error, setError] = useState(null)
  const editar = puede(yo, 'personal', 'editar')

  const cargar = useCallback(() => api('/api/personal').then(setLista), [])
  useEffect(() => {
    cargar()
    if (puede(yo, 'roles')) api('/api/roles').then(setRoles)
    if (puede(yo, 'padron')) api('/api/padron/estructura').then((e) => setTurnos(e.turnos))
  }, [cargar, yo])

  async function cambiarTurno(p, turno) {
    setError(null)
    try {
      await api(`/api/personal/${p.id}`, { metodo: 'PUT', datos: {
        nombres: p.nombres, apellidos: p.apellidos, rol_id: p.rol_id, activo: p.activo,
        turno_id: turno ? Number(turno) : null } })
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function carnets() {
    setError(null)
    try { await descargar('/api/personal/carnets', 'carnets-personal.pdf') } catch (err) { setError(err.message) }
  }

  async function crear(e) {
    e.preventDefault()
    setError(null)
    try {
      const r = await api('/api/personal', { metodo: 'POST', datos: { ...nuevo, rol_id: Number(nuevo.rol_id) } })
      setClave({ quien: `${r.personal.nombres} ${r.personal.apellidos}`, usuario: r.personal.usuario, clave: r.clave_temporal })
      setNuevo(vacio)
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function reiniciar(p) {
    if (!confirm(`¿Reiniciar la clave de ${p.nombres} ${p.apellidos}?`)) return
    const r = await api(`/api/personal/${p.id}/reiniciar-clave`, { metodo: 'POST' })
    setClave({ quien: `${p.nombres} ${p.apellidos}`, usuario: p.usuario, clave: r.clave_temporal })
  }

  return (
    <section>
      <h2>Personal</h2>
      {clave && (
        <div className="aviso">
          Clave temporal de <b>{clave.quien}</b> (usuario {clave.usuario}): <code>{clave.clave}</code>
          <br /><span className="tenue">Se muestra una sola vez. La cambiará al primer ingreso.</span>
          <button className="enlace" onClick={() => setClave(null)}>Cerrar</button>
        </div>
      )}
      <table>
        <thead><tr><th>Documento</th><th>Nombre</th><th>Rol</th><th>Turno</th><th>Estado</th>{editar && <th />}</tr></thead>
        <tbody>
          {lista.map((p) => (
            <tr key={p.id}>
              <td>{p.tipo_documento} {p.numero_documento}</td><td>{p.apellidos}, {p.nombres}</td><td>{p.rol}</td>
              <td>
                {editar && turnos.length > 0
                  ? <select value={p.turno_id ?? ''} onChange={(e) => cambiarTurno(p, e.target.value)} aria-label="Turno">
                      <option value="">Sin turno</option>
                      {turnos.map((t) => <option key={t.id} value={t.id}>{t.nombre} ({t.hora_entrada})</option>)}
                    </select>
                  : turnos.find((t) => t.id === p.turno_id)?.nombre || (p.turno_id ? 'Con turno' : 'Sin turno')}
              </td>
              <td>{!p.activo ? 'Inactivo' : p.debe_cambiar_clave ? 'Clave temporal' : 'Activo'}</td>
              {editar && <td><button className="enlace" onClick={() => reiniciar(p)}>Reiniciar clave</button></td>}
            </tr>
          ))}
        </tbody>
      </table>
      {editar && (
        <div className="fila-form">
          <button className="boton secundario" onClick={carnets}>Carnets del personal (PDF)</button>
          <span className="tenue">Con el turno asignado, la portería calcula su tardanza y su falta automática.</span>
        </div>
      )}
      {editar && roles.length > 0 && (
        <form className="fila-form" onSubmit={crear}>
          <select value={nuevo.tipo_documento} onChange={(e) => setNuevo({ ...nuevo, tipo_documento: e.target.value })}>
            <option value="DNI">DNI</option>
            <option value="CE">Carné de extranjería</option>
          </select>
          <input placeholder="N° de documento" value={nuevo.numero_documento} required
                 inputMode={nuevo.tipo_documento === 'DNI' ? 'numeric' : 'text'}
                 pattern={nuevo.tipo_documento === 'DNI' ? '\\d{8}' : '[A-Za-z0-9]{9,12}'}
                 onChange={(e) => setNuevo({ ...nuevo, numero_documento: e.target.value })} />
          <input placeholder="Nombres" value={nuevo.nombres} required
                 onChange={(e) => setNuevo({ ...nuevo, nombres: e.target.value })} />
          <input placeholder="Apellidos" value={nuevo.apellidos} required
                 onChange={(e) => setNuevo({ ...nuevo, apellidos: e.target.value })} />
          <select value={nuevo.rol_id} required onChange={(e) => setNuevo({ ...nuevo, rol_id: e.target.value })}>
            <option value="">Rol…</option>
            {roles.filter((r) => !r.es_director || yo.es_director).map((r) =>
              <option key={r.id} value={r.id}>{r.nombre}</option>)}
          </select>
          <button className="boton">Agregar</button>
          {error && <p className="error">{error}</p>}
        </form>
      )}
    </section>
  )
}

function Roles({ yo }) {
  const [roles, setRoles] = useState([])
  const [modulos, setModulos] = useState({})
  const [editando, setEditando] = useState(null)
  const [error, setError] = useState(null)
  const editar = puede(yo, 'roles', 'editar')

  const cargar = useCallback(() => api('/api/roles').then(setRoles), [])
  useEffect(() => { cargar(); api('/api/roles/modulos').then(setModulos) }, [cargar])

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    const permisos = Object.fromEntries(Object.entries(editando.permisos).filter(([, n]) => n))
    try {
      if (editando.id) await api(`/api/roles/${editando.id}`, { metodo: 'PUT', datos: { nombre: editando.nombre, permisos } })
      else await api('/api/roles', { metodo: 'POST', datos: { nombre: editando.nombre, permisos } })
      setEditando(null)
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function borrar(r) {
    if (!confirm(`¿Borrar el rol ${r.nombre}?`)) return
    try { await api(`/api/roles/${r.id}`, { metodo: 'DELETE' }); cargar() } catch (err) { setError(err.message) }
  }

  return (
    <section>
      <h2>Roles y permisos</h2>
      <ul className="lista">
        {roles.map((r) => (
          <li key={r.id}>
            <b>{r.nombre}</b>{' '}
            <span className="tenue">{r.es_director ? 'Todos los permisos' : Object.keys(r.permisos).map((m) => modulos[m] || m).join(', ') || 'Sin permisos'}</span>
            {editar && !r.es_director && <>
              {' '}<button className="enlace" onClick={() => setEditando({ ...r })}>Editar</button>
              <button className="enlace" onClick={() => borrar(r)}>Borrar</button>
            </>}
          </li>
        ))}
      </ul>
      {editar && !editando && <button className="boton" onClick={() => setEditando({ nombre: '', permisos: {} })}>Nuevo rol</button>}
      {editando && (
        <form onSubmit={guardar} className="tarjeta ancho">
          <label>Nombre del rol
            <input value={editando.nombre} required onChange={(e) => setEditando({ ...editando, nombre: e.target.value })} />
          </label>
          <table>
            <thead><tr><th>Módulo</th><th>Sin acceso</th><th>Ver</th><th>Editar</th></tr></thead>
            <tbody>
              {Object.entries(modulos).map(([clave, nombre]) => (
                <tr key={clave}>
                  <td>{nombre}</td>
                  {['', 'ver', 'editar'].map((n) => (
                    <td key={n}>
                      <input type="radio" name={clave} checked={(editando.permisos[clave] || '') === n}
                             onChange={() => setEditando({ ...editando, permisos: { ...editando.permisos, [clave]: n } })} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {error && <p className="error">{error}</p>}
          <div className="acciones">
            <button className="boton">Guardar</button>
            <button type="button" className="enlace" onClick={() => setEditando(null)}>Cancelar</button>
          </div>
        </form>
      )}
    </section>
  )
}

function Imagen({ yo, colegio, setColegio }) {
  const [colores, setColores] = useState({ color_primario: colegio.color_primario, color_secundario: colegio.color_secundario })
  const [mensaje, setMensaje] = useState(null)
  const editar = puede(yo, 'configuracion', 'editar')

  function aplicar(c) { setColegio(c); aplicarImagen(c) }

  async function guardarColores(e) {
    e.preventDefault()
    aplicar(await api('/api/colegio/imagen', { metodo: 'PUT', datos: colores }))
    setMensaje('Colores guardados')
  }

  async function subirLogo(e) {
    const archivo = e.target.files[0]
    if (!archivo) return
    try { aplicar(await api('/api/colegio/logo', { metodo: 'PUT', archivo })); setMensaje('Logo actualizado') }
    catch (err) { setMensaje(err.message) }
    e.target.value = ''
  }

  async function quitarLogo() {
    aplicar(await api('/api/colegio/logo', { metodo: 'DELETE' }))
    setMensaje('Logo quitado')
  }

  return (
    <section>
      <h2>Imagen del colegio</h2>
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
      {mensaje && <p className="tenue">{mensaje}</p>}
    </section>
  )
}
