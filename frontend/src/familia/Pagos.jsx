// Pagos de la familia: cuotas de cada hijo (estado, saldo, vencimiento) y los recibos de lo pagado.
// Solo para el apoderado responsable de pago. Es información: la deuda no bloquea nada. Sin pago en línea.
import { Receipt } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, descargar } from '../api.js'
import { fechaCorta, soles } from '../espacios/comun/index.js'

const ESTADO = { pendiente: ['Pendiente', 'neutro'], parcial: ['Pago parcial', 'justificada'], pagada: ['Pagada', 'a-tiempo'],
  vencida: ['Vencida', 'falta'] }

export default function PagosFamilia() {
  const { yo } = useOutletContext()
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const apagado = yo?.modulos?.pensiones === false
  const activa = yo?.estado === 'activo'
  useEffect(() => {
    if (!yo || apagado || !activa) return
    api('/api/familia/pagos').then(setD).catch((e) => setError(e.message))
  }, [yo, apagado, activa])

  if (apagado) return <p className="tenue">El colegio no muestra los pagos en la app.</p>
  if (yo && !activa) return <p className="tenue">Los pagos se ven cuando el colegio aprueba su cuenta.</p>
  return (
    <>
      <div className="saludo"><h1>Pagos</h1></div>
      {error && <p className="error">{error}</p>}
      {!d && !error && <p className="tenue">Cargando…</p>}
      {d && d.hijos.length === 0 && (
        <section className="tarjeta-app">
          <p className="tenue">Los pagos los ve el apoderado responsable de pago. Si debe ser usted, pídalo en secretaría.</p>
        </section>
      )}
      {d?.hijos.map((h) => <PagosHijo key={h.id} h={h} varios={d.hijos.length > 1} />)}
    </>
  )
}

function PagosHijo({ h, varios }) {
  const [error, setError] = useState(null)
  const porPagar = h.cuotas.filter((c) => c.estado !== 'pagada')
  const pagadas = h.cuotas.filter((c) => c.estado === 'pagada')
  return (
    <section className="tarjeta-app pagos-hijo">
      {varios && <h2>{h.nombres}</h2>}
      <div className="resumen-pagos">
        <div><b>{soles(h.saldo)}</b><span className="tenue">Por pagar en el año</span></div>
        <div className={Number(h.vencido) > 0 ? 'vencido' : undefined}><b>{soles(h.vencido)}</b><span className="tenue">Vencido</span></div>
      </div>
      {porPagar.length === 0 ? <p className="tenue">Todo al día. ¡Gracias!</p> : (
        <ul className="dias-mes cuotas-familia">
          {porPagar.map((c) => (
            <li key={c.id}>
              <span><b>{c.concepto} · {c.mes}</b><small className="tenue">Vence el {fechaCorta(c.vence)}</small></span>
              <span className="numero">{soles(c.saldo)}
                {Number(c.mora) > 0 && <small className="tenue">incluye mora {soles(c.mora)}</small>}</span>
              <span className={`chip-estado ${ESTADO[c.estado][1]}`}>{ESTADO[c.estado][0]}</span>
            </li>
          ))}
        </ul>
      )}
      {pagadas.length > 0 && <p className="tenue">{pagadas.length} {pagadas.length === 1 ? 'cuota pagada' : 'cuotas pagadas'}.</p>}
      {h.pagos.length > 0 && (
        <>
          <h3>Recibos</h3>
          <ul className="dias-mes recibos-familia">
            {h.pagos.map((p) => (
              <li key={p.id}>
                <span><b>{p.recibo}</b><small className="tenue">{fechaCorta(p.fecha)} · {p.cuotas.join(', ')}</small></span>
                <span className="numero">{soles(p.total)}</span>
                <button type="button" className="boton-icono" aria-label={`Descargar recibo ${p.recibo}`}
                        onClick={() => descargar(`/api/familia/pagos/${p.id}/recibo.pdf`, `recibo-${p.recibo}.pdf`).catch((e) => setError(e.message))}>
                  <Receipt aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {error && <p className="error">{error}</p>}
      <p className="tenue nota-pagos">Se paga en la caja del colegio. Si ve algo que no cuadra, consulte en secretaría.</p>
    </section>
  )
}
