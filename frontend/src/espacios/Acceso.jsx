import { Link } from 'react-router-dom'
import { iniciales } from '../tema.js'
import './acceso.css'

// Logo del colegio o sus iniciales en un cuadro.
export function Logo({ colegio, className = '' }) {
  return colegio.logo_url
    ? <img src={colegio.logo_url} alt="" className={`logo ${className}`} />
    : <span className={`logo logo-iniciales ${className}`} aria-hidden="true">{iniciales(colegio.nombre)}</span>
}

// Pantalla de ingreso en dos mitades: el colegio con su color a la izquierda, el formulario a la derecha.
export default function Acceso({ colegio, children }) {
  return (
    <div className="acceso">
      <aside className="acceso-marca">
        <div className="acceso-colegio">
          <Logo colegio={colegio} className="acceso-logo" />
          <span className="acceso-nombre">{colegio.nombre}</span>
        </div>
        <Escena />
        <span className="forma forma-circulo" aria-hidden="true" />
        <span className="forma forma-cuadro" aria-hidden="true" />
      </aside>
      <main className="acceso-panel">
        <div className="acceso-contenido">{children}</div>
        <footer className="acceso-pie">
          <span>Plataforma de Tikray Labs</span>
          <Link to="/privacidad">Privacidad y datos personales</Link>
          <Link to="/ayuda">Ayuda</Link>
        </footer>
      </main>
    </div>
  )
}

// Patrón fijo de 9×9 para dibujar un QR (solo decorativo).
const QR = [
  '111111101', '100000101', '101110100', '101110111', '100000010',
  '111111011', '000100110', '110111001', '101010111',
]

// Carnet con QR que se lee y un celular donde caen los avisos. Ciclo de 9 s, todo en CSS.
function Escena() {
  return (
    <div className="escena" role="img"
         aria-label="Un carnet escolar con código QR se acerca al lector de la puerta y se marca con un check verde. En el celular del padre llegan tres avisos: Mateo ingresó a las 7:38 a. m., un nuevo comunicado del cuaderno de control sobre la reunión de padres y Mateo salió del colegio.">
      <div className="escena-carnet" aria-hidden="true">
        <div className="carnet-cabeza">
          <span className="carnet-foto" />
          <span className="carnet-lineas"><i /><i /><i /></span>
        </div>
        <div className="carnet-qr">
          {QR.join('').split('').map((v, i) => <span key={i} className={v === '1' ? 'lleno' : ''} />)}
          <span className="carnet-escaneo" />
        </div>
        <span className="carnet-check">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="3"
               strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
        </span>
      </div>
      <div className="escena-celular" aria-hidden="true">
        <span className="celular-muesca" />
        <span className="celular-hora">7:38</span>
        <div className="celular-avisos">
          <Notificacion n={1} app="Asistencia" texto="Mateo ingresó a las 7:38 a. m." />
          <Notificacion n={2} app="Cuaderno de control" texto="Nuevo comunicado: reunión de padres" />
          <Notificacion n={3} app="Asistencia" texto="Mateo salió del colegio" />
        </div>
      </div>
    </div>
  )
}

function Notificacion({ n, app, texto }) {
  return (
    <div className={`notificacion notificacion-${n}`}>
      <span className="notificacion-icono" />
      <span className="notificacion-texto">
        <b>{app}</b>
        <span>{texto}</span>
      </span>
      <span className="notificacion-cuando">ahora</span>
    </div>
  )
}
