import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import './asistencia.css'
import './resumen.css'

const TIPOS = { justificacion: 'Justificaciones', permiso_salida: 'Permisos de salida', citacion: 'Citaciones',
  comunicado: 'Comunicados', incidencia: 'Incidencias' }

const diaSemana = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-PE', { weekday: 'short' }).replace('.', '')
const diaCorto = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-PE', { weekday: 'short', day: 'numeric' })

function Cifra({ valor, texto, a }) {
  const cuerpo = <><strong>{valor}</strong><span>{texto}</span></>
  return a ? <Link className="total cifra-enlace" to={a}>{cuerpo}</Link> : <div className="total">{cuerpo}</div>
}

// Asistencia de los últimos días de clase: una sola serie (el % que vino), barras desde cero.
function Tendencia({ dias }) {
  if (!dias.some((d) => d.registrados)) return <p className="tenue">Aún no hay días con asistencia registrada.</p>
  return (
    <figure className="tendencia">
      <figcaption>Asistencia en los últimos días de clase (% que vino, puntual o tarde)</figcaption>
      <div className="tendencia-barras" role="list">
        {dias.map((d) => (
          <div key={d.fecha} className="tendencia-dia" role="listitem"
               title={d.registrados ? `${diaCorto(d.fecha)}: ${d.porcentaje}% (${d.vino} de ${d.registrados})` : `${diaCorto(d.fecha)}: sin registros`}>
            <span className="tendencia-valor">{d.porcentaje ?? '—'}{d.porcentaje != null && '%'}</span>
            <div className="tendencia-pista"><div className="tendencia-barra" style={{ height: `${d.porcentaje || 0}%` }} /></div>
            <span className="tendencia-fecha">{diaSemana(d.fecha)}<b>{Number(d.fecha.slice(8))}</b></span>
          </div>
        ))}
      </div>
    </figure>
  )
}

export default function Resumen({ yo }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let vivo = true
    const cargar = () => api('/api/panel/resumen').then((r) => vivo && setD(r)).catch((e) => vivo && setError(e.message))
    cargar()
    const t = setInterval(cargar, 60000)  // la mañana cambia rápido: se refresca solo cada minuto
    return () => { vivo = false; clearInterval(t) }
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!d) return <p className="tenue">Cargando…</p>
  const a = d.asistencia, c = d.cuaderno, f = d.familias
  const porAprobar = c ? Object.values(c.por_aprobar).reduce((x, y) => x + y, 0) : 0

  return (
    <div className="resumen">
      <h2>Bienvenido, {yo.nombres}</h2>
      <p className="tenue">{new Date(`${d.fecha}T12:00:00`).toLocaleDateString('es-PE', { dateStyle: 'full' })}</p>

      {a && (
        <section>
          <h3>Asistencia de hoy</h3>
          {!a.lectivo && <p className="aviso-chico">Hoy no es día de clases.</p>}
          {a.lectivo && (
            <div className="totales">
              <Cifra valor={a.porcentaje == null ? '—' : `${a.porcentaje}%`} texto={`vino de ${a.alumnos} alumnos`} a="/panel/asistencia" />
              <Cifra valor={a.hoy.presente} texto="puntuales" />
              <Cifra valor={a.hoy.tarde} texto="tardanzas" />
              <Cifra valor={a.hoy.falta} texto="faltas" />
              <Cifra valor={a.hoy.justificada} texto="faltas justificadas" />
              <Cifra valor={a.hoy.sin_registro} texto="aún sin marcar" />
            </div>
          )}
          <div className="resumen-columnas">
            <Tendencia dias={a.tendencia} />
            <div>
              <h4>Secciones con más faltas hoy</h4>
              {a.secciones_con_faltas.length ? (
                <ol className="resumen-lista">
                  {a.secciones_con_faltas.map((s) => <li key={s.id}><span>{s.nombre}</span><strong>{s.faltas}</strong></li>)}
                </ol>
              ) : <p className="tenue">Ninguna falta sin justificar.</p>}
              <h4>Personal hoy</h4>
              <p>{a.personal.presente} puntuales · {a.personal.tarde} tarde · {a.personal.falta} faltas · {a.personal.licencia} con licencia</p>
            </div>
          </div>
        </section>
      )}

      {c && (
        <section>
          <h3>Cuaderno de control</h3>
          <div className="totales">
            <Cifra valor={porAprobar} texto="pendientes de aprobar" a="/panel/cuaderno" />
            <Cifra valor={c.sin_responder} texto="hilos con respuesta de la familia" a="/panel/cuaderno" />
          </div>
          {porAprobar > 0 && (
            <p className="tenue">{Object.entries(c.por_aprobar).map(([t, n]) => `${TIPOS[t] || t}: ${n}`).join(' · ')}</p>
          )}
          {c.firmas.length > 0 && (
            <>
              <h4>Firmas de lectura</h4>
              <ul className="resumen-lista">
                {c.firmas.map((e) => {
                  const p = e.apoderados ? Math.round(100 * e.firmados / e.apoderados) : 0
                  return (
                    <li key={e.id}>
                      <Link to={`/panel/cuaderno/${e.id}`}>{e.titulo || TIPOS[e.tipo]}</Link>
                      <span className="firma">
                        <span className="firma-pista"><span style={{ width: `${p}%` }} /></span>
                        {e.firmados} de {e.apoderados}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </section>
      )}

      {f && (
        <section>
          <h3>Familias y avisos</h3>
          <div className="totales">
            <Cifra valor={`${f.activos} de ${f.apoderados}`} texto="apoderados con cuenta activa" a="/panel/familias" />
            <Cifra valor={f.con_notificaciones} texto="reciben notificaciones" />
            <Cifra valor={f.pendientes} texto="esperan aprobación" a="/panel/familias" />
            <Cifra valor={f.sin_cuenta} texto="sin cuenta todavía" />
            <Cifra valor={f.avisos_hoy.enviado} texto="avisos enviados hoy" />
            <Cifra valor={f.avisos_en_cola} texto="avisos en cola" />
          </div>
          {f.avisos_hoy.error > 0 && <p className="error">{f.avisos_hoy.error} avisos fallaron hoy.</p>}
        </section>
      )}

      {!a && !c && !f && <p className="tenue">Elige un módulo en el menú.</p>}
    </div>
  )
}
