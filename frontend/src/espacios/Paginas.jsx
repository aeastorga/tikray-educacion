// Páginas informativas del pie del ingreso.
import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import Cabecera from './Cabecera.jsx'

function Pagina({ colegio, titulo, children }) {
  return (
    <main className="centro">
      <article className="tarjeta ancho pagina-texto">
        <Cabecera colegio={colegio} />
        <Link to="/" className="enlace acceso-volver"><ArrowLeft size={18} aria-hidden="true" /> Volver al ingreso</Link>
        <h2>{titulo}</h2>
        {children}
      </article>
    </main>
  )
}

export function Privacidad({ colegio }) {
  return (
    <Pagina colegio={colegio} titulo="Privacidad y datos personales">
      <p>Los datos de alumnos, apoderados y personal pertenecen a <b>{colegio.nombre}</b>, que es el titular del banco de
        datos según la Ley 29733 de Protección de Datos Personales. Tikray Labs es el encargado del tratamiento: guarda y
        procesa los datos solo por encargo del colegio y para prestar este servicio.</p>
      <ul className="lista">
        <li>Se usan para la asistencia, los avisos a las familias y el cuaderno de control.</li>
        <li>El consentimiento de cada apoderado queda guardado con su fecha al activar su cuenta.</li>
        <li>Los datos de huella o rostro nunca llegan a la plataforma: el equipo solo envía el código del alumno y la hora.</li>
        <li>Los avisos se envían como notificaciones del celular; no se comparten con terceros.</li>
      </ul>
      <p>Para consultar, corregir o eliminar sus datos, o retirar su consentimiento, acérquese a la secretaría del colegio.</p>
    </Pagina>
  )
}

export function Ayuda({ colegio }) {
  return (
    <Pagina colegio={colegio} titulo="Ayuda">
      <h3>Soy padre o apoderado</h3>
      <ul className="lista">
        <li><b>Primera vez:</b> abra el enlace personal que el colegio le envió por WhatsApp y cree su PIN de 6 números.</li>
        <li><b>Olvidé mi PIN o no tengo enlace:</b> pida uno nuevo en secretaría.</li>
        <li><b>No me llegan los avisos:</b> en iPhone, agregue la página a la pantalla de inicio y ábrala desde ahí; luego
          toque “Activar avisos”.</li>
      </ul>
      <h3>Soy personal del colegio</h3>
      <ul className="lista">
        <li>Su usuario es su DNI. La primera vez usará una clave temporal y el sistema le pedirá cambiarla.</li>
        <li>Si olvidó su clave, dirección o secretaría le da una nueva.</li>
      </ul>
    </Pagina>
  )
}
