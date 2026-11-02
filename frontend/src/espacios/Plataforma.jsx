import { useCallback, useEffect, useState } from 'react'
import { api, guardarToken, leerToken } from '../api.js'

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

const VACIO = { nombre: '', subdominio: '', dni: '', nombres: '', apellidos: '' }

function Colegios({ salir }) {
  const [lista, setLista] = useState([])
  const [nuevo, setNuevo] = useState(VACIO)
  const [creado, setCreado] = useState(null)
  const [error, setError] = useState(null)

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
          director: { dni: nuevo.dni, nombres: nuevo.nombres, apellidos: nuevo.apellidos },
        },
      })
      setCreado(r)
      setNuevo(VACIO)
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function alternar(c) {
    const accion = c.activo ? 'suspender' : 'reactivar'
    if (!confirm(`¿${accion[0].toUpperCase() + accion.slice(1)} ${c.nombre}?`)) return
    await api(`/plataforma/colegios/${c.id}`, { metodo: 'PATCH', datos: { activo: !c.activo } })
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
            Colegio <b>{creado.colegio.nombre}</b> creado. Director: usuario <code>{creado.director_usuario}</code>,
            clave temporal <code>{creado.director_clave_temporal}</code>
            <br /><span className="tenue">Se muestra una sola vez.</span>
            <button className="enlace" onClick={() => setCreado(null)}>Cerrar</button>
          </div>
        )}
        <table>
          <thead><tr><th>Colegio</th><th>Dirección</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {lista.map((c) => (
              <tr key={c.id}>
                <td>{c.nombre}</td>
                <td><a href={`//${c.subdominio}.${base}`} target="_blank" rel="noreferrer">{c.subdominio}.{base}</a>
                  {c.dominio_propio && <> · {c.dominio_propio}</>}</td>
                <td>{c.activo ? 'Activo' : 'Suspendido'}</td>
                <td><button className="enlace" onClick={() => alternar(c)}>{c.activo ? 'Suspender' : 'Reactivar'}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <h2>Nuevo colegio</h2>
        <form className="fila-form" onSubmit={crear}>
          <input placeholder="Nombre del colegio" required {...campo('nombre')} />
          <input placeholder="subdominio" required pattern="[a-z0-9]([a-z0-9\-]*[a-z0-9])?" {...campo('subdominio')} />
          <input placeholder="DNI del director" required inputMode="numeric" pattern="\d{8}" {...campo('dni')} />
          <input placeholder="Nombres del director" required {...campo('nombres')} />
          <input placeholder="Apellidos del director" required {...campo('apellidos')} />
          <button className="boton">Crear</button>
          {error && <p className="error">{error}</p>}
        </form>
      </main>
    </div>
  )
}
