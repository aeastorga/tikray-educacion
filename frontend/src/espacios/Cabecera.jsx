import { Logo } from './Acceso.jsx'

export default function Cabecera({ colegio, children }) {
  return (
    <header className="cabecera">
      <Logo colegio={colegio} />
      <h1>{colegio.nombre}</h1>
      {children}
    </header>
  )
}
