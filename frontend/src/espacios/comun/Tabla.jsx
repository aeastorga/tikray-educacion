import './tabla.css'

const INTERACTIVO = 'button, a, input, select, textarea, label, [role="menu"]'

// Tabla común del panel. En celular (menos de 760 px) cada fila es una tarjeta: la primera columna arriba
// en negrita, el resto como "etiqueta: valor" en dos columnas y las acciones abajo, a todo el ancho.
// columnas: [{ id, titulo, celda, ancho, alinear, ocultarEnCelular, acciones, numero, nowrap, claseCelda }]
export default function Tabla({ columnas, filas, clave = (f) => f.id, alFila, vacio, cargando, etiqueta, claseFila }) {
  if (!cargando && filas && filas.length === 0 && vacio) return <Vacio {...vacio} />
  const lista = cargando || !filas ? null : filas
  return (
    <div className="tabla-caja">
      <table className="tabla" aria-label={etiqueta} aria-busy={cargando ? 'true' : undefined}>
        <colgroup>{columnas.map((c) => <col key={c.id} style={c.ancho ? { width: c.ancho } : undefined} />)}</colgroup>
        <thead>
          <tr>
            {columnas.map((c) => (
              <th key={c.id} scope="col" className={clases(c)}>
                {c.acciones ? <span className="solo-lectores">{c.titulo || 'Acciones'}</span> : c.titulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {!lista && Array.from({ length: 5 }, (_, i) => (
            <tr key={`esqueleto-${i}`} className="esqueleto" aria-hidden="true">
              {columnas.map((c) => <td key={c.id} className={clases(c)}><span /></td>)}
            </tr>
          ))}
          {lista && lista.map((f) => {
            const abrir = alFila ? () => alFila(f) : undefined
            return (
              <tr key={clave(f)} className={[alFila ? 'clic' : '', claseFila?.(f) || ''].join(' ').trim() || undefined}
                  tabIndex={alFila ? 0 : undefined}
                  onClick={abrir && ((e) => { if (!e.target.closest(INTERACTIVO)) abrir() })}
                  onKeyDown={abrir && ((e) => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); abrir() } })}>
                {columnas.map((c, i) => (
                  <td key={c.id} className={[clases(c, i), c.claseCelda?.(f)].filter(Boolean).join(' ') || undefined} data-etiqueta={c.acciones || i === 0 ? undefined : c.titulo}>
                    {c.celda(f)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function clases(c, i) {
  return [
    i === 0 && 'principal', c.acciones && 'acciones-celda', c.numero && 'numero',
    c.alinear && `alinear-${c.alinear}`, c.ocultarEnCelular && 'ocultar-celular', c.nowrap && 'nowrap',
  ].filter(Boolean).join(' ') || undefined
}

// Nunca una tabla vacía con solo encabezados.
export function Vacio({ icono: Icono, titulo, texto, accion }) {
  return (
    <div className="vacio">
      {Icono && <span className="vacio-icono"><Icono size={32} aria-hidden="true" /></span>}
      <h3>{titulo}</h3>
      {texto && <p className="tenue">{texto}</p>}
      {accion}
    </div>
  )
}
