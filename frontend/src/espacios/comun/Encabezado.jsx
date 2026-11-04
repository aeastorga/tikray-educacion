export default function Encabezado({ titulo, descripcion, acciones, nivel = 2 }) {
  const H = `h${nivel}`
  return (
    <header className="encabezado">
      <div className="encabezado-texto">
        <H>{titulo}</H>
        {descripcion && <p className="tenue">{descripcion}</p>}
      </div>
      {acciones && <div className="encabezado-acciones">{acciones}</div>}
    </header>
  )
}
