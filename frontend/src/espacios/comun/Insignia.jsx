// Estado como pastilla con un punto de color: bien, tarde, falta, neutro, info.
export default function Insignia({ tono = 'neutro', icono: Icono, children, titulo }) {
  return (
    <span className={`insignia ${tono}`} title={titulo}>
      {Icono ? <Icono size={14} aria-hidden="true" /> : <i aria-hidden="true" />}
      {children}
    </span>
  )
}
