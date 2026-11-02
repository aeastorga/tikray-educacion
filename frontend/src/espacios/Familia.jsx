import { Link } from 'react-router-dom'
import Cabecera from './Cabecera.jsx'

// El ingreso de familias (enlace personal + DNI + PIN o huella) llega en el paso 3.
export default function Familia({ colegio }) {
  return (
    <main className="centro">
      <div className="tarjeta">
        <Cabecera colegio={colegio} />
        <p>
          Para entrar necesitas el enlace personal que te envía el colegio por WhatsApp.
          Si no lo tienes, pídelo en secretaría.
        </p>
        <Link to="/" className="enlace">Volver</Link>
      </div>
    </main>
  )
}
