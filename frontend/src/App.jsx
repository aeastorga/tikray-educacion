import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, ErrorApi, esPlataforma } from './api.js'
import Ingreso from './espacios/Ingreso.jsx'
import IngresoPersonal from './espacios/IngresoPersonal.jsx'
import Familia from './espacios/Familia.jsx'
import PanelColegio from './espacios/PanelColegio.jsx'
import Plataforma from './espacios/Plataforma.jsx'

export function aplicarImagen(imagen) {
  const raiz = document.documentElement.style
  raiz.setProperty('--primario', imagen.color_primario)
  raiz.setProperty('--secundario', imagen.color_secundario)
  document.title = imagen.nombre
}

export default function App() {
  const [colegio, setColegio] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (esPlataforma) return
    api('/api/publico/colegio')
      .then((c) => {
        setColegio(c)
        aplicarImagen(c)
        try { localStorage.setItem('tikray.colegio', JSON.stringify(c)) } catch { /* modo privado */ }
      })
      .catch((e) => {
        // Sin internet (portería): la última imagen conocida del colegio.
        let guardado = null
        try { guardado = !(e instanceof ErrorApi) && JSON.parse(localStorage.getItem('tikray.colegio')) } catch { /* nada */ }
        if (guardado) { setColegio(guardado); aplicarImagen(guardado); return }
        setError(e.estado === 404 ? 'Esta dirección no corresponde a ningún colegio.' : e.message)
      })
    // 403 = colegio suspendido o vencido: el mensaje del servidor ya lo explica.
  }, [])

  if (esPlataforma) return <Plataforma />
  if (error) return <main className="centro"><p>{error}</p></main>
  if (!colegio) return <main className="centro"><p className="tenue">Cargando…</p></main>

  return (
    <Routes>
      <Route path="/" element={<Ingreso colegio={colegio} />} />
      <Route path="/personal" element={<IngresoPersonal colegio={colegio} />} />
      <Route path="/familia/*" element={<Familia colegio={colegio} />} />
      <Route path="/panel/*" element={<PanelColegio colegio={colegio} setColegio={setColegio} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
