import { useState } from 'react'
import { api, guardarToken } from '../api.js'
import { Mensaje } from './comun/index.js'

export default function CambiarClave({ alTerminar, obligatorio }) {
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [repetida, setRepetida] = useState('')
  const [error, setError] = useState(null)
  const [motivos, setMotivos] = useState([])

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    setMotivos([])
    if (nueva !== repetida) return setError('Las claves nuevas no coinciden')
    try {
      const r = await api('/api/auth/cambiar-clave', {
        metodo: 'POST', datos: { clave_actual: actual, clave_nueva: nueva },
      })
      guardarToken(r.token)
      alTerminar()
    } catch (err) {
      setError(err.message)
      setMotivos(err.motivos)
    }
  }

  return (
    <form className="tarjeta" onSubmit={enviar}>
      <h2>{obligatorio ? 'Crea tu clave personal' : 'Cambiar clave'}</h2>
      {obligatorio && <p className="tenue">Tu clave es temporal. Cámbiala para continuar.</p>}
      <label>Clave actual
        <input type="password" value={actual} onChange={(e) => setActual(e.target.value)}
               autoComplete="current-password" required />
      </label>
      <label>Clave nueva
        <input type="password" value={nueva} onChange={(e) => setNueva(e.target.value)}
               autoComplete="new-password" required />
      </label>
      <label>Repite la clave nueva
        <input type="password" value={repetida} onChange={(e) => setRepetida(e.target.value)}
               autoComplete="new-password" required />
      </label>
      <p className="tenue">Al menos 8 caracteres, con mayúscula, minúscula y número.</p>
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      {motivos.length > 0 && <ul className="error">{motivos.map((m) => <li key={m}>{m}</li>)}</ul>}
      <button className="boton">Guardar</button>
    </form>
  )
}
