import { BriefcaseBusiness, ChevronRight, UsersRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import Acceso from './Acceso.jsx'

export default function Ingreso({ colegio }) {
  return (
    <Acceso colegio={colegio}>
      <h1>Bienvenido</h1>
      <p className="acceso-subtitulo">¿Cómo quiere ingresar?</p>
      <nav className="opciones-ingreso" aria-label="Tipo de ingreso">
        <Link to="/familia" className="opcion-ingreso">
          <span className="opcion-icono"><UsersRound size={26} aria-hidden="true" /></span>
          <span className="opcion-texto">
            <b>Soy padre o apoderado</b>
            <span>Con su PIN o la huella de su celular</span>
          </span>
          <ChevronRight className="opcion-flecha" aria-hidden="true" />
        </Link>
        <Link to="/personal" className="opcion-ingreso">
          <span className="opcion-icono"><BriefcaseBusiness size={26} aria-hidden="true" /></span>
          <span className="opcion-texto">
            <b>Soy personal del colegio</b>
            <span>Dirección, docentes, portería y secretaría</span>
          </span>
          <ChevronRight className="opcion-flecha" aria-hidden="true" />
        </Link>
      </nav>
      <p className="acceso-nota">
        <b>¿Primera vez?</b> Abra el enlace que el colegio le envió por WhatsApp. Si no lo tiene, pídalo en secretaría.
      </p>
    </Acceso>
  )
}
