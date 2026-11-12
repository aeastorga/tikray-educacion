import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { ProveedorDialogos } from './espacios/comun/Dialogo.jsx'
import { instalarEnvio } from './envio.js'
// Fuentes dentro de la app (solo latín y los pesos que se usan): sin depender de Google y sin internet.
import '@fontsource/bricolage-grotesque/latin-600.css'
import '@fontsource/bricolage-grotesque/latin-700.css'
import '@fontsource/bricolage-grotesque/latin-800.css'
import '@fontsource/plus-jakarta-sans/latin-400.css'
import '@fontsource/plus-jakarta-sans/latin-500.css'
import '@fontsource/plus-jakarta-sans/latin-600.css'
import '@fontsource/plus-jakarta-sans/latin-700.css'
import './estilos.css'

instalarEnvio()
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <ProveedorDialogos>
        <App />
      </ProveedorDialogos>
    </BrowserRouter>
  </StrictMode>,
)
