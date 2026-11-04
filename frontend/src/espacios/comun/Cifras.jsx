export default function Cifras({ items }) {
  const visibles = items.filter(Boolean)
  if (!visibles.length) return null
  return (
    <dl className="cifras">
      {visibles.map((c) => (
        <div key={c.etiqueta} className={`cifra ${c.tono || ''}`}>
          <dd>{typeof c.valor === 'number' ? c.valor.toLocaleString('es-PE') : c.valor}</dd>
          <dt className="tenue">{c.etiqueta}</dt>
        </div>
      ))}
    </dl>
  )
}
