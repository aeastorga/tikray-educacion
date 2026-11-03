import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, guardarToken, leerToken } from '../api.js'
import Cabecera from './Cabecera.jsx'

export default function IngresoPersonal({ colegio }) {
  const navegar = useNavigate()
  const [params] = useSearchParams()
  // Volver a donde estaba (p. ej. la portería tras una sesión vencida); solo rutas del panel.
  const volver = /^\/panel(\/[\w/-]*)?$/.test(params.get('volver') || '') ? params.get('volver') : '/panel'
  const [usuario, setUsuario] = useState('')
  const [clave, setClave] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)

  if (leerToken()) return <Navigate to={volver} replace />

  async function enviar(e) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      const r = await api('/api/auth/ingreso', { metodo: 'POST', datos: { usuario, clave } })
      guardarToken(r.token)
      navegar(volver, { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <main className="centro">
      <form className="tarjeta" onSubmit={enviar}>
        <Cabecera colegio={colegio} />
        <label>Usuario (DNI)
          <input value={usuario} onChange={(e) => setUsuario(e.target.value)} inputMode="numeric"
                 autoComplete="username" required />
        </label>
        <label>Clave
          <input type="password" value={clave} onChange={(e) => setClave(e.target.value)}
                 autoComplete="current-password" required />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="boton" disabled={enviando}>{enviando ? 'Ingresando…' : 'Ingresar'}</button>
        <Link to="/" className="enlace">Volver</Link>
      </form>
    </main>
  )
}
