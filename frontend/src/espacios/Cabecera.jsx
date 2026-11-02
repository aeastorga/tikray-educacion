export default function Cabecera({ colegio, children }) {
  return (
    <header className="cabecera">
      {colegio.logo_url
        ? <img src={colegio.logo_url} alt="" className="logo" />
        : <div className="logo logo-iniciales">{iniciales(colegio.nombre)}</div>}
      <h1>{colegio.nombre}</h1>
      {children}
    </header>
  )
}

function iniciales(nombre) {
  return nombre.split(/\s+/).filter((p) => p.length > 2).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
}
