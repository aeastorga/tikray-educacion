import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { api, descargar, ErrorApi, guardarToken, leerToken } from '../api.js'
import { borrarPadron } from '../porteria/almacen.js'
import { KeyRound, ShieldCheck, Users } from 'lucide-react'
import Asistencia from './Asistencia.jsx'
import Caja from './Caja.jsx'
import {
  documento, Encabezado, Insignia, MenuAcciones, Paginacion, Persona, Tabla, usePaginaLocal,
} from './comun/index.js'
import CambiarClave from './CambiarClave.jsx'
import Configuracion, { Historial } from './Configuracion.jsx'
import Menu from './Menu.jsx'
import Cuaderno from './Cuaderno.jsx'
import CuentasPadres from './CuentasPadres.jsx'
import Padron from './Padron.jsx'
import Pensiones from './Pensiones.jsx'
import Resumen from './Resumen.jsx'
import Reunion from './Reunion.jsx'

const NIVEL = { ver: 1, editar: 2 }
export const puede = (yo, modulo, nivel = 'ver') => (NIVEL[yo.permisos[modulo]] || 0) >= NIVEL[nivel]
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
    <div className="marco">
      <Menu colegio={colegio} yo={yo} puede={(m, n) => puede(yo, m, n)} salir={salir} />
      <main className="contenido">
        <Routes>
          <Route index element={<Resumen yo={yo} puede={(m, n) => puede(yo, m, n)} />} />
          <Route path="asistencia/*" element={<Asistencia yo={yo} marcar={puede(yo, 'asistencia', 'editar')}
            licencias={puede(yo, 'personal', 'editar')} reglas={puede(yo, 'configuracion', 'editar')} />} />
          <Route path="cuaderno/*" element={<Cuaderno editar={puede(yo, 'cuaderno', 'editar')}
            docentes={puede(yo, 'padron', 'editar')} />} />
          {puede(yo, 'pensiones') && <Route path="pensiones/*" element={<Pensiones editar={puede(yo, 'pensiones', 'editar')} />} />}
          {puede(yo, 'caja') && <Route path="caja/*" element={<Caja editar={puede(yo, 'caja', 'editar')} />} />}
          <Route path="padron/*" element={<Padron editar={puede(yo, 'padron', 'editar')} />} />
          <Route path="familias/*" element={<CuentasPadres colegio={colegio} editar={puede(yo, 'familias', 'editar')}
            reglas={puede(yo, 'configuracion', 'editar')} />} />
          <Route path="reunion/*" element={<Reunion colegio={colegio} editar={puede(yo, 'reuniones', 'editar')} />} />
          <Route path="personal" element={<Personal yo={yo} />} />
          <Route path="roles" element={<Roles yo={yo} />} />
          <Route path="configuracion/*" element={<Configuracion editar={puede(yo, 'configuracion', 'editar')}
            colegio={colegio} setColegio={setColegio} recargarYo={cargar} />} />
          {yo.es_director && <Route path="historial" element={<Historial />} />}
          <Route path="imagen" element={<Navigate to="/panel/configuracion" replace />} />
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

  const pagina = usePaginaLocal(lista)

  async function reiniciar(p) {
    if (!confirm(`¿Reiniciar la clave de ${p.nombres} ${p.apellidos}?`)) return
    const r = await api(`/api/personal/${p.id}/reiniciar-clave`, { metodo: 'POST' })
    setClave({ quien: `${p.nombres} ${p.apellidos}`, usuario: p.usuario, clave: r.clave_temporal })
  }

  return (
    <section>
      <Encabezado titulo="Personal" descripcion="Con el turno asignado, la portería calcula su tardanza y su falta automática."
                  acciones={editar && <button className="boton secundario" onClick={carnets}>Carnets del personal (PDF)</button>} />
      {clave && (
        <div className="aviso">
          Clave temporal de <b>{clave.quien}</b> (usuario {clave.usuario}): <code>{clave.clave}</code>
          <br /><span className="tenue">Se muestra una sola vez. La cambiará al primer ingreso.</span>
          <button className="enlace" onClick={() => setClave(null)}>Cerrar</button>
        </div>
      )}
      <Tabla etiqueta="Personal" filas={pagina.filas}
             vacio={{ icono: Users, titulo: 'Todavía no hay personal', texto: editar ? 'Agrégalo con el formulario de abajo o desde Excel.' : null }}
             columnas={[
               { id: 'persona', titulo: 'Nombre', ancho: '30%',
                 celda: (p) => <Persona nombre={`${p.apellidos}, ${p.nombres}`} detalle={documento(p.tipo_documento, p.numero_documento)} /> },
               { id: 'rol', titulo: 'Rol', celda: (p) => p.rol },
               { id: 'turno', titulo: 'Turno', celda: (p) => (editar && turnos.length > 0
                 ? <select value={p.turno_id ?? ''} onChange={(e) => cambiarTurno(p, e.target.value)} aria-label={`Turno de ${p.nombres} ${p.apellidos}`}>
                     <option value="">Sin turno</option>
                     {turnos.map((t) => <option key={t.id} value={t.id}>{t.nombre} ({t.hora_entrada})</option>)}
                   </select>
                 : turnos.find((t) => t.id === p.turno_id)?.nombre || (p.turno_id ? 'Con turno' : 'Sin turno')) },
               { id: 'estado', titulo: 'Estado', celda: (p) => (!p.activo ? <Insignia tono="neutro">Inactivo</Insignia>
                 : p.debe_cambiar_clave ? <Insignia tono="tarde">Clave temporal</Insignia> : <Insignia tono="bien">Activo</Insignia>) },
               editar && { id: 'acciones', acciones: true, celda: (p) => (
                 <MenuAcciones etiqueta={`${p.nombres} ${p.apellidos}`}
                               principal={{ texto: 'Reiniciar clave', icono: KeyRound, alHacer: () => reiniciar(p) }} />
               ) },
             ].filter(Boolean)} />
      {pagina.paginacion && <Paginacion {...pagina.paginacion} />}
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
      const datos = { nombre: editando.nombre, permisos, solo_sus_secciones: Boolean(editando.solo_sus_secciones),
        puede_anular_caja: Boolean(editando.puede_anular_caja) }
      if (editando.id) await api(`/api/roles/${editando.id}`, { metodo: 'PUT', datos })
      else await api('/api/roles', { metodo: 'POST', datos })
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
      <Encabezado titulo="Roles y permisos" descripcion="Cada rol decide qué módulos ve o edita quien lo tiene."
                  acciones={editar && !editando && (
                    <button className="boton" onClick={() => setEditando({ nombre: '', permisos: {}, solo_sus_secciones: false, puede_anular_caja: false })}>Nuevo rol</button>
                  )} />
      <Tabla etiqueta="Roles" filas={roles}
             vacio={{ icono: ShieldCheck, titulo: 'Sin roles' }}
             columnas={[
               { id: 'rol', titulo: 'Rol', ancho: '24%', celda: (r) => <b>{r.nombre}</b> },
               { id: 'permisos', titulo: 'Permisos', celda: (r) => (
                 <>
                   {r.es_director ? 'Todos los permisos' : Object.keys(r.permisos).map((m) => modulos[m] || m).join(', ') || <span className="tenue">Sin permisos</span>}
                   {r.solo_sus_secciones && <span className="segunda-linea">Solo sus secciones</span>}
                   {r.puede_anular_caja && <span className="segunda-linea">Puede anular pagos y gastos pasados</span>}
                 </>
               ) },
               editar && { id: 'acciones', acciones: true, celda: (r) => (!r.es_director && (
                 <MenuAcciones etiqueta={r.nombre} principal={{ texto: 'Editar', alHacer: () => setEditando({ ...r }) }}
                               opciones={[{ texto: 'Borrar', peligro: true, alHacer: () => borrar(r) }]} />
               )) },
             ].filter(Boolean)} />
      {editando && (
        <form onSubmit={guardar} className="tarjeta ancho">
          <label>Nombre del rol
            <input value={editando.nombre} required onChange={(e) => setEditando({ ...editando, nombre: e.target.value })} />
          </label>
          <Tabla etiqueta="Permisos del rol" filas={Object.entries(modulos)} clave={([clave]) => clave}
                 columnas={[
                   { id: 'modulo', titulo: 'Módulo', celda: ([, nombre]) => nombre },
                   ...[['', 'Sin acceso'], ['ver', 'Ver'], ['editar', 'Editar']].map(([n, titulo]) => ({
                     id: n || 'nada', titulo, alinear: 'centro', celda: ([clave, nombre]) => (
                       <input type="radio" name={clave} aria-label={`${nombre}: ${titulo}`} checked={(editando.permisos[clave] || '') === n}
                              onChange={() => setEditando({ ...editando, permisos: { ...editando.permisos, [clave]: n } })} />
                     ),
                   })),
                 ]} />
          <label className="check">
            <input type="checkbox" checked={Boolean(editando.solo_sus_secciones)}
                   onChange={(e) => setEditando({ ...editando, solo_sus_secciones: e.target.checked })} />
            Solo ve las secciones a su cargo (cuaderno de control: docentes y tutores)
          </label>
          <label className="check">
            <input type="checkbox" checked={Boolean(editando.puede_anular_caja)}
                   onChange={(e) => setEditando({ ...editando, puede_anular_caja: e.target.checked })} />
            Puede anular pagos de caja cerrada y gastos de días anteriores
          </label>
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
