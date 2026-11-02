import { Link } from 'react-router-dom'
import Cabecera from './Cabecera.jsx'

export default function Ingreso({ colegio }) {
  return (
    <main className="centro">
      <div className="tarjeta">
        <Cabecera colegio={colegio} />
        <div className="botones-ingreso">
          <Link to="/familia" className="boton grande">Soy padre o apoderado</Link>
          <Link to="/personal" className="boton grande secundario">Soy personal del colegio</Link>
        </div>
      </div>
    </main>
  )
}
