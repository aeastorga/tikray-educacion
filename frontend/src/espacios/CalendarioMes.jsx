// Piezas del calendario escolar que comparten el panel y la app de la familia: la cuadrícula del mes (lunes a
// domingo, con los días sin clases), la lista de próximos y el detalle de un evento. Fechas de Lima (AAAA-MM-DD).
import { ChevronLeft, ChevronRight, Clock, Users } from 'lucide-react'
import { useMemo } from 'react'
import './calendario.css'

const DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
  'noviembre', 'diciembre']
const DIAS_LARGOS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

const aFecha = (iso) => new Date(`${iso}T12:00:00Z`)
const iso = (d) => d.toISOString().slice(0, 10)

export function sumarMes(mes, n) {
  const [a, m] = mes.split('-').map(Number)
  const d = new Date(Date.UTC(a, m - 1 + n, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}

export function nombreMes(mes) {
  const [a, m] = mes.split('-').map(Number)
  return `${MESES[m - 1].charAt(0).toUpperCase()}${MESES[m - 1].slice(1)} ${a}`
}

// "Viernes 14 de noviembre" o "Del 14 al 16 de noviembre".
export function cuando(e) {
  const i = aFecha(e.inicio)
  const texto = (d) => `${d.getUTCDate()} de ${MESES[d.getUTCMonth()]}`
  if (e.inicio === e.fin) {
    const t = `${DIAS_LARGOS[i.getUTCDay()]} ${texto(i)}`
    return t.charAt(0).toUpperCase() + t.slice(1)
  }
  const f = aFecha(e.fin)
  return i.getUTCMonth() === f.getUTCMonth() ? `Del ${i.getUTCDate()} al ${texto(f)}` : `Del ${texto(i)} al ${texto(f)}`
}

export function NavegarMes({ mes, cambiar, hoy }) {
  const actual = hoy?.slice(0, 7)
  return (
    <div className="navegar-mes">
      <button type="button" className="boton-icono" aria-label="Mes anterior" onClick={() => cambiar(sumarMes(mes, -1))}>
        <ChevronLeft aria-hidden="true" />
      </button>
      <h3 aria-live="polite">{nombreMes(mes)}</h3>
      <button type="button" className="boton-icono" aria-label="Mes siguiente" onClick={() => cambiar(sumarMes(mes, 1))}>
        <ChevronRight aria-hidden="true" />
      </button>
      {actual && actual !== mes && <button type="button" className="enlace" onClick={() => cambiar(actual)}>Hoy</button>}
    </div>
  )
}

// Cuadrícula del mes. `elegido` es el día abierto abajo (AAAA-MM-DD).
export function MesCalendario({ mes, hoy, eventos, sinClases, elegido, elegir }) {
  const semanas = useMemo(() => {
    const primero = aFecha(`${mes}-01`)
    const inicio = new Date(primero)
    inicio.setUTCDate(1 - ((primero.getUTCDay() + 6) % 7))  // el lunes de esa semana
    const filas = []
    const d = new Date(inicio)
    do {
      const semana = []
      for (let i = 0; i < 7; i++) { semana.push(iso(d)); d.setUTCDate(d.getUTCDate() + 1) }
      filas.push(semana)
    } while (iso(d).slice(0, 7) === mes)
    return filas
  }, [mes])
  const libres = useMemo(() => Object.fromEntries(sinClases.map((s) => [s.fecha, s.motivo])), [sinClases])
  const delDia = (dia) => eventos.filter((e) => e.inicio <= dia && dia <= e.fin)

  return (
    <div className="mes-calendario" role="grid" aria-label={`Calendario de ${nombreMes(mes)}`}>
      <div className="mes-fila mes-cabeza" role="row">
        {DIAS.map((d) => <span key={d} role="columnheader">{d}</span>)}
      </div>
      {semanas.map((semana) => (
        <div className="mes-fila" role="row" key={semana[0]}>
          {semana.map((dia) => {
            const fuera = dia.slice(0, 7) !== mes
            const lista = fuera ? [] : delDia(dia)
            const libre = !fuera && libres[dia]
            const clases = ['mes-dia', fuera && 'fuera', dia === hoy && 'hoy', libre && 'libre', dia === elegido && 'elegido']
            const etiqueta = [`${Number(dia.slice(8))} de ${MESES[Number(dia.slice(5, 7)) - 1]}`,
              libre && `sin clases: ${libre}`, lista.length && `${lista.length} evento${lista.length > 1 ? 's' : ''}`]
            return (
              <button key={dia} type="button" role="gridcell" className={clases.filter(Boolean).join(' ')}
                      disabled={fuera} aria-pressed={dia === elegido} aria-label={etiqueta.filter(Boolean).join(', ')}
                      onClick={() => elegir(dia === elegido ? null : dia)}>
                <span className="mes-numero">{Number(dia.slice(8))}</span>
                {libre && <span className="mes-libre">Sin clases</span>}
                <span className="mes-eventos">
                  {lista.slice(0, 3).map((e) => (
                    <span key={e.id} className={`mes-evento tipo-${e.tipo}${e.anulado ? ' anulado' : ''}`}>
                      {e.hora && <b>{e.hora}</b>} {e.titulo}
                    </span>
                  ))}
                  {lista.length > 3 && <span className="mes-mas">+{lista.length - 3}</span>}
                </span>
                {lista.length > 0 && (
                  <span className="mes-puntos" aria-hidden="true">
                    {lista.slice(0, 4).map((e) => <i key={e.id} className={`tipo-${e.tipo}${e.anulado ? ' anulado' : ''}`} />)}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      ))}
    </div>
  )
}

// Un evento: título, cuándo, a quién va (y a cuáles de sus hijos, en la familia), anulado con motivo.
export function TarjetaEvento({ e, acciones, hijos }) {
  return (
    <article className={`tarjeta-evento tipo-${e.tipo}${e.anulado ? ' anulado' : ''}`}>
      <div className="tarjeta-evento-cabeza">
        <span className="chip-tipo">{e.tipo_nombre}</span>
        {e.anulado && <span className="chip-anulado">Anulado</span>}
      </div>
      <h4>{e.titulo}</h4>
      <p className="tarjeta-evento-cuando">
        <Clock size={15} aria-hidden="true" /> {cuando(e)}{e.hora ? ` · ${e.hora}` : ''}
      </p>
      <p className="tarjeta-evento-para">
        <Users size={15} aria-hidden="true" /> {hijos && e.hijos ? `Para ${e.hijos.join(' y ')} · ${e.para}` : e.para}
      </p>
      {e.descripcion && <p className="tarjeta-evento-texto">{e.descripcion}</p>}
      {e.anulado && e.anulado_motivo && <p className="tarjeta-evento-motivo">Motivo: {e.anulado_motivo}</p>}
      {acciones}
    </article>
  )
}

// Lo del día elegido en la cuadrícula: el día sin clases y sus eventos.
export function DetalleDia({ dia, eventos, sinClases, accionesDe, hijos, vacio = 'Nada este día.' }) {
  const libre = sinClases.find((s) => s.fecha === dia)
  const lista = eventos.filter((e) => e.inicio <= dia && dia <= e.fin)
  return (
    <section className="detalle-dia" aria-label={cuando({ inicio: dia, fin: dia })}>
      <h3>{cuando({ inicio: dia, fin: dia })}</h3>
      {libre && <p className="aviso-libre">Sin clases: {libre.motivo}</p>}
      {!libre && lista.length === 0 && <p className="tenue">{vacio}</p>}
      <div className="lista-eventos">
        {lista.map((e) => <TarjetaEvento key={e.id} e={e} hijos={hijos} acciones={accionesDe?.(e)} />)}
      </div>
    </section>
  )
}

// Próximos: eventos y días sin clases, en orden de fecha y agrupados por mes.
export function ListaProximos({ eventos, sinClases, accionesDe, hijos, vacio = 'No hay eventos próximos.' }) {
  const items = [
    ...eventos.map((e) => ({ fecha: e.inicio, e })),
    ...sinClases.map((s) => ({ fecha: s.fecha, libre: s })),
  ].sort((a, b) => a.fecha.localeCompare(b.fecha) || (a.libre ? -1 : 1))
  if (items.length === 0) return <p className="tenue">{vacio}</p>
  const grupos = []
  for (const it of items) {
    const mes = it.fecha.slice(0, 7)
    if (!grupos.length || grupos[grupos.length - 1].mes !== mes) grupos.push({ mes, items: [] })
    grupos[grupos.length - 1].items.push(it)
  }
  return grupos.map((g) => (
    <section key={g.mes} className="proximos-mes" aria-label={nombreMes(g.mes)}>
      <h3>{nombreMes(g.mes)}</h3>
      <div className="lista-eventos">
        {g.items.map((it) => (it.libre
          ? <p key={`l${it.fecha}`} className="aviso-libre">{cuando({ inicio: it.fecha, fin: it.fecha })} · Sin clases: {it.libre.motivo}</p>
          : <TarjetaEvento key={it.e.id} e={it.e} hijos={hijos} acciones={accionesDe?.(it.e)} />))}
      </div>
    </section>
  ))
}
