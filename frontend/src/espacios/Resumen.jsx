// Inicio del director: cómo va el colegio hoy, en una pantalla. Cada bloque sale solo con su permiso.
import {
  Bell, ClipboardList, FileSpreadsheet, MessageCircle, Plus, QrCode, ScanLine, Search, Send, UserCheck,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { hora12, LIMA, saludo } from '../tema.js'
import './inicio.css'

const TIPOS = { justificacion: 'Justificaciones', permiso_salida: 'Permisos de salida', citacion: 'Citaciones',
  comunicado: 'Comunicados', incidencia: 'Incidencias' }
const ESTADO_PERMISO = { pendiente: 'Por aprobar', aprobada: 'Aprobado' }

function useReloj() {
  const [ahora, setAhora] = useState(() => new Date())
  useEffect(() => { const t = setInterval(() => setAhora(new Date()), 30000); return () => clearInterval(t) }, [])
  return ahora
}

export default function Resumen({ yo, puede }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const ahora = useReloj()

  useEffect(() => {
    let vivo = true
    const cargar = () => api('/api/panel/resumen').then((r) => vivo && setD(r)).catch((e) => vivo && setError(e.message))
    cargar()
    const t = setInterval(cargar, 60000)  // la mañana cambia rápido: se refresca solo cada minuto
    return () => { vivo = false; clearInterval(t) }
  }, [])

  const fecha = ahora.toLocaleDateString('es-PE', { timeZone: LIMA, weekday: 'long', day: 'numeric', month: 'long' })
  const hora = ahora.toLocaleTimeString('es-PE', { timeZone: LIMA, hour: 'numeric', minute: '2-digit' })

  return (
    <div className="inicio">
      <header className="inicio-cabecera">
        <div>
          <p className="inicio-fecha"><time>{fecha.charAt(0).toUpperCase() + fecha.slice(1)} · {hora}</time></p>
          <h1>{saludo(ahora)}, {yo.nombres.split(' ')[0]}</h1>
        </div>
        <div className="inicio-herramientas">
          {puede('padron') && <Buscador />}
          {d && <Campana d={d} />}
          {puede('cuaderno', 'editar') && (
            <Link to="/panel/cuaderno/escribir" className="boton"><Plus size={18} aria-hidden="true" /> Nuevo comunicado</Link>
          )}
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {!d && !error && <p className="tenue">Cargando…</p>}
      {d && <Tablero d={d} puede={puede} />}
    </div>
  )
}

function Tablero({ d, puede }) {
  const a = d.asistencia, c = d.cuaderno, f = d.familias
  if (!a && !c && !f) return <p className="tenue">Elija un módulo en el menú.</p>
  return (
    <>
      {(a || f) && (
        <div className="fila fila-1">
          {a && <IngresoDeHoy a={a} />}
          {f && <AvisosFamilias f={f} invitar={puede('familias')} />}
        </div>
      )}
      {a && a.lectivo && (
        <div className="fila fila-2">
          <Llegadas ll={a.llegadas} />
          <MasFaltas secciones={a.secciones_con_faltas} />
        </div>
      )}
      <div className="fila fila-3">
        {d.personal && <Personal p={d.personal} />}
        {c && <CuadernoHoy c={c} />}
        <Accesos puede={puede} />
      </div>
    </>
  )
}

// --- Fila 1 ----------------------------------------------------------------------------------

function IngresoDeHoy({ a }) {
  const pct = a.porcentaje ?? 0
  const cajas = [
    ['a-tiempo', 'A tiempo', a.hoy.presente],
    ['tarde', 'Tardanzas', a.hoy.tarde],
    ['falta', 'Faltas', a.hoy.falta],
    ['justificada', 'Justificadas', a.hoy.justificada],
  ]
  return (
    <section className="caja caja-ingreso" aria-labelledby="t-ingreso">
      <div className="caja-cabeza">
        <h2 id="t-ingreso">Ingreso de hoy{a.solo_sus_secciones && <small className="solo-secciones">Tus secciones</small>}</h2>
        {a.ultima_marcacion && (
          <span className="etiqueta-viva">
            <i aria-hidden="true" />Última marcación {hora12(a.ultima_marcacion.hora)}
            {a.ultima_marcacion.equipo ? ` · ${a.ultima_marcacion.equipo}` : a.ultima_marcacion.origen === 'manual' ? ' · manual' : ''}
          </span>
        )}
      </div>
      {!a.lectivo ? <p className="tenue">Hoy no es día de clases.</p> : (
        <div className="ingreso-cuerpo">
          <div className="anillo" style={{ '--pct': pct }} role="img"
               aria-label={`Asistencia: ${a.porcentaje ?? 0} % (${a.hoy.presente + a.hoy.tarde} de ${a.alumnos} alumnos)`}>
            <div className="anillo-centro">
              <b>{a.porcentaje == null ? '—' : `${a.porcentaje}%`}</b>
              <span>asistencia</span>
            </div>
          </div>
          <div className="ingreso-datos">
            <p className="tenue ingreso-total">
              Vinieron <b>{a.hoy.presente + a.hoy.tarde}</b> de {a.alumnos} alumnos
              {a.hoy.sin_registro > 0 && <> · {a.hoy.sin_registro} aún sin marcar</>}
            </p>
            <div className="cajas-estado">
              {cajas.map(([clase, texto, valor]) => (
                <Link key={clase} to="/panel/asistencia" className={`caja-numero ${clase}`}>
                  <b>{valor}</b><span>{texto}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

function AvisosFamilias({ f, invitar }) {
  const av = f.avisos_hoy
  const procesados = av.enviado + av.sin_notificaciones + av.error
  const pct = procesados ? Math.round(100 * av.enviado / procesados) : 0
  const sinApp = f.apoderados - f.activos
  const boton = invitar && sinApp > 0 && (
    <Link to="/panel/familias" className="boton boton-claro"><Send size={18} aria-hidden="true" /> Invitar por WhatsApp</Link>
  )
  if (f.con_notificaciones === 0 && av.enviado === 0) {
    return (
      <section className="caja caja-oscura" aria-labelledby="t-avisos">
        <h2 id="t-avisos">Avisos a familias</h2>
        <p className="avisos-vacio">Ningún apoderado tiene los avisos activos todavía.</p>
        <p className="avisos-nota">Cuando activen la app en su celular, aquí verá cuántos avisos les llegan cada día.</p>
        <div className="avisos-sin-app">
          <p><b>{sinApp}</b> {sinApp === 1 ? 'apoderado sin la app' : 'apoderados sin la app'}
            {f.pendientes > 0 && <> · {f.pendientes} esperan aprobación</>}</p>
          {boton}
        </div>
      </section>
    )
  }
  return (
    <section className="caja caja-oscura" aria-labelledby="t-avisos">
      <h2 id="t-avisos">Avisos a familias</h2>
      <p className="avisos-cifra"><b>{av.enviado}</b> <span>avisos entregados hoy</span></p>
      <div className="barra-avance" role="img" aria-label={`${pct} % de los avisos de hoy llegaron a un celular`}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <dl className="avisos-cifras">
        <div><dt>Entregados</dt><dd>{av.enviado}</dd></div>
        <div><dt>Por enviar</dt><dd>{f.avisos_en_cola}</dd></div>
        <div><dt>Sin app</dt><dd>{sinApp}</dd></div>
      </dl>
      {(av.sin_notificaciones > 0 || av.error > 0) && (
        <ul className="avisos-detalle">
          {av.sin_notificaciones > 0 && <li>{av.sin_notificaciones} no llegaron: el apoderado no tiene las notificaciones activas</li>}
          {av.error > 0 && <li className="avisos-error">{av.error} fallaron</li>}
        </ul>
      )}
      <div className="avisos-sin-app">
        <p>{f.con_notificaciones} {f.con_notificaciones === 1 ? 'apoderado recibe' : 'apoderados reciben'} los avisos
          {f.pendientes > 0 && <> · {f.pendientes} esperan aprobación</>}</p>
        {boton}
      </div>
    </section>
  )
}

// --- Fila 2: llegadas por tramo y faltas por sección ------------------------------------------

function Llegadas({ ll }) {
  const tramos = ll.tramos
  const max = Math.max(1, ...tramos.map((t) => t.a_tiempo + t.tarde))
  const escala = Math.max(5, Math.ceil(max / 5) * 5)
  const etiquetaCada = Math.max(1, Math.ceil(tramos.length / 8))
  // Dónde va la línea de tolerancia: entre el último tramo que empieza antes y el primero que empieza después.
  const iLimite = ll.limite ? tramos.findIndex((t) => t.inicio >= ll.limite) : -1
  const fin = (inicio) => {
    const [h, m] = inicio.split(':').map(Number)
    const x = h * 60 + m + ll.tramo_minutos
    return `${String(Math.floor(x / 60)).padStart(2, '0')}:${String(x % 60).padStart(2, '0')}`
  }
  return (
    <section className="caja caja-llegadas" aria-labelledby="t-llegadas">
      <div className="caja-cabeza">
        <h2 id="t-llegadas">Llegadas por hora</h2>
        <ul className="leyenda">
          <li><i className="muestra a-tiempo" aria-hidden="true" />A tiempo</li>
          <li><i className="muestra tarde" aria-hidden="true" />Después de la tolerancia</li>
          {ll.limite && <li><i className="muestra linea" aria-hidden="true" />Tolerancia {hora12(ll.limite)}</li>}
        </ul>
      </div>
      {tramos.length === 0 ? <p className="tenue">Aún no hay ingresos hoy.</p> : (
        <>
          <div className="grafico" aria-hidden="true">
            <div className="grafico-eje">
              <span>{escala}</span><span>{Math.round(escala / 2)}</span><span>0</span>
            </div>
            <div className="grafico-barras" style={{ '--n': tramos.length }}>
              {tramos.map((t, i) => {
                const total = t.a_tiempo + t.tarde
                return (
                  <div key={t.inicio} className={`grafico-tramo ${i === iLimite ? 'con-limite' : ''}`}>
                    <div className="grafico-pila" style={{ height: `${100 * total / escala}%` }}>
                      {t.tarde > 0 && <span className="pila-tarde" style={{ flexGrow: t.tarde }} />}
                      {t.a_tiempo > 0 && <span className="pila-a-tiempo" style={{ flexGrow: t.a_tiempo }} />}
                    </div>
                    <div className="grafico-tooltip">
                      <b>{hora12(t.inicio)} – {hora12(fin(t.inicio))}</b>
                      <span>{t.a_tiempo} a tiempo</span>
                      {t.tarde > 0 && <span>{t.tarde} después de la tolerancia</span>}
                    </div>
                    <span className="grafico-x">{i % etiquetaCada === 0 ? t.inicio.replace(/^0/, '') : ''}</span>
                  </div>
                )
              })}
            </div>
          </div>
          <table className="solo-lectores">
            <caption>Llegadas por tramo de {ll.tramo_minutos} minutos</caption>
            <thead><tr><th>Tramo</th><th>A tiempo</th><th>Después de la tolerancia</th></tr></thead>
            <tbody>{tramos.map((t) => <tr key={t.inicio}><td>{hora12(t.inicio)}</td><td>{t.a_tiempo}</td><td>{t.tarde}</td></tr>)}</tbody>
          </table>
        </>
      )}
    </section>
  )
}

function MasFaltas({ secciones }) {
  const max = Math.max(1, ...secciones.map((s) => s.faltas))
  return (
    <section className="caja" aria-labelledby="t-faltas">
      <h2 id="t-faltas">Más faltas hoy</h2>
      {secciones.length === 0 ? <p className="tenue">Ninguna falta sin justificar.</p> : (
        <ol className="lista-faltas">
          {secciones.map((s) => (
            <li key={s.id}>
              <span className="lista-faltas-nombre">{s.nombre}</span>
              <span className="barra-falta" aria-hidden="true"><span style={{ width: `${100 * s.faltas / max}%` }} /></span>
              <b>{s.faltas}</b>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

// --- Fila 3 ----------------------------------------------------------------------------------

function Personal({ p }) {
  const presentes = p.presente + p.tarde
  const tipo = { salud: 'salud', personal: 'personal', vacaciones: 'vacaciones', comision: 'comisión',
    maternidad: 'maternidad', otro: 'otro' }
  const grupos = [
    ['Licencias', p.lista.licencias.map((x) => [x.nombre, tipo[x.tipo] || x.tipo]), p.con_licencia, 'licencia'],
    ['Tardanzas', p.lista.tardanzas.map((x) => [x.nombre, `${x.minutos} min`]), p.tarde, 'tarde'],
    ['Sin marcar', p.lista.sin_marcar.map((x) => [x.nombre, '']), p.sin_marcar, 'sin-marcar'],
  ].filter(([, lista]) => lista.length)
  return (
    <section className="caja" aria-labelledby="t-personal">
      <div className="caja-cabeza">
        <h2 id="t-personal">Personal</h2>
        <Link to="/panel/asistencia/personal" className="enlace-chico">Ver todo</Link>
      </div>
      <p className="cifra-grande"><b>{presentes}</b> <span>de {p.total} presentes</span></p>
      {grupos.length === 0 && <p className="tenue">Sin novedades.</p>}
      {grupos.map(([titulo, lista, total, clase]) => (
        <div key={titulo} className="lista-corta">
          <h3>{titulo} <span className={`contador ${clase}`}>{total}</span></h3>
          <ul>
            {lista.map(([nombre, nota]) => <li key={nombre}><span>{nombre}</span>{nota && <small>{nota}</small>}</li>)}
            {total > lista.length && <li className="tenue">y {total - lista.length} más</li>}
          </ul>
        </div>
      ))}
    </section>
  )
}

function CuadernoHoy({ c }) {
  const ultimo = c.firmas.find((e) => e.tipo === 'comunicado') || c.firmas[0]
  const pct = ultimo?.apoderados ? Math.round(100 * ultimo.firmados / ultimo.apoderados) : 0
  const justificaciones = c.por_aprobar.justificacion || 0
  const otros = Object.entries(c.por_aprobar).filter(([t]) => t !== 'justificacion' && t !== 'permiso_salida')
  return (
    <section className="caja" aria-labelledby="t-cuaderno">
      <div className="caja-cabeza">
        <h2 id="t-cuaderno">Cuaderno de control</h2>
        <Link to="/panel/cuaderno" className="enlace-chico">Bandeja</Link>
      </div>
      {ultimo ? (
        <Link to={`/panel/cuaderno/${ultimo.id}`} className="ultimo-comunicado">
          <small className="tenue">{ultimo.tipo === 'citacion' ? 'Última citación' : 'Último comunicado'}</small>
          <b>{ultimo.titulo}</b>
          <span className="firma-avance">
            <span className="barra-avance clara" aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
            <span>{pct}% firmó · {ultimo.firmados} de {ultimo.apoderados}</span>
          </span>
        </Link>
      ) : <p className="tenue">Aún no hay comunicados con firma.</p>}
      <Link to="/panel/cuaderno" className="fila-enlace">
        <span>Justificaciones por revisar</span><b className={justificaciones ? 'contador tarde' : 'contador'}>{justificaciones}</b>
      </Link>
      {otros.map(([t, n]) => (
        <Link key={t} to="/panel/cuaderno" className="fila-enlace"><span>{TIPOS[t]} por aprobar</span><b className="contador">{n}</b></Link>
      ))}
      {c.sin_responder > 0 && (
        <Link to="/panel/cuaderno" className="fila-enlace">
          <span className="icono-texto"><MessageCircle size={16} aria-hidden="true" /> Respuestas de familias</span><b className="contador">{c.sin_responder}</b>
        </Link>
      )}
      <h3 className="subtitulo">Permisos de salida de hoy</h3>
      {c.permisos_salida_hoy.length === 0 ? <p className="tenue">Ninguno.</p> : (
        <ul className="salidas-hoy">
          {c.permisos_salida_hoy.map((s) => (
            <li key={s.id}>
              <Link to={`/panel/cuaderno/${s.id}`}><b>{hora12(s.hora)}</b> {s.alumno}</Link>
              <small className={`chip-mini ${s.estado}`}>{ESTADO_PERMISO[s.estado] || s.estado}</small>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Accesos({ puede }) {
  const accesos = [
    puede('asistencia', 'editar') && ['/panel/asistencia/porteria', 'Marcación manual', ScanLine],
    puede('asistencia') && ['/panel/asistencia', 'Reporte del día', ClipboardList],
    puede('padron', 'editar') && ['/panel/padron/importar', 'Cargar Excel', FileSpreadsheet],
    puede('padron') && ['/panel/padron/secciones', 'Carnets QR', QrCode],
    puede('familias') && ['/panel/familias', 'Cuentas de padres', UserCheck],
  ].filter(Boolean).slice(0, 4)
  if (!accesos.length) return null
  return (
    <section className="caja" aria-labelledby="t-accesos">
      <h2 id="t-accesos">Accesos rápidos</h2>
      <div className="accesos">
        {accesos.map(([a, texto, Icono]) => (
          <Link key={a + texto} to={a} className="acceso-rapido">
            <span className="acceso-icono"><Icono size={22} aria-hidden="true" /></span>{texto}
          </Link>
        ))}
      </div>
    </section>
  )
}

// --- Cabecera: buscador y campana ---------------------------------------------------------------

function Buscador() {
  const navegar = useNavigate()
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const caja = useRef(null)

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return undefined }
    const t = setTimeout(() => {
      api(`/api/padron/alumnos?q=${encodeURIComponent(q.trim())}&limite=6`).then(setRes).catch(() => setRes(null))
    }, 250)
    return () => clearTimeout(t)
  }, [q])
  useCerrarFuera(caja, () => setRes(null))

  const ir = (a) => navegar(`/panel/padron?alumno=${a.id}`)
  return (
    <div className="buscador" ref={caja} role="search">
      <Search size={18} className="buscador-icono" aria-hidden="true" />
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar alumno por nombre o DNI"
             placeholder="Alumno: nombre o DNI" aria-controls="resultados-alumno" aria-expanded={Boolean(res)}
             onKeyDown={(e) => { if (e.key === 'Enter' && res?.alumnos[0]) ir(res.alumnos[0]); if (e.key === 'Escape') setRes(null) }} />
      {res && (
        <ul id="resultados-alumno" className="buscador-resultados">
          {res.alumnos.length === 0 && <li className="tenue">Sin resultados</li>}
          {res.alumnos.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => ir(a)}>
                <b>{a.apellidos}, {a.nombres}</b>
                <small>{a.tipo_documento} {a.numero_documento}{a.seccion ? ` · ${a.seccion}` : ''}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Campana({ d }) {
  const [abierta, setAbierta] = useState(false)
  const caja = useRef(null)
  useCerrarFuera(caja, () => setAbierta(false))
  const c = d.cuaderno, f = d.familias
  const porAprobar = c ? Object.values(c.por_aprobar).reduce((x, y) => x + y, 0) : 0
  const items = [
    porAprobar > 0 && ['/panel/cuaderno', `${porAprobar} pendientes de aprobar en el cuaderno`],
    c?.sin_responder > 0 && ['/panel/cuaderno', `${c.sin_responder} respuestas de familias`],
    f?.pendientes > 0 && ['/panel/familias', `${f.pendientes} apoderados esperan aprobación`],
    f?.avisos_hoy.error > 0 && ['/panel/familias', `${f.avisos_hoy.error} avisos fallaron hoy`],
  ].filter(Boolean)
  return (
    <div className="campana" ref={caja}>
      <button type="button" className="boton-icono" aria-label={`Avisos: ${items.length} pendientes`} aria-expanded={abierta}
              onClick={() => setAbierta(!abierta)}>
        <Bell size={20} aria-hidden="true" />
        {items.length > 0 && <span className="campana-punto" aria-hidden="true">{items.length}</span>}
      </button>
      {abierta && (
        <div className="campana-lista" role="dialog" aria-label="Pendientes">
          {items.length === 0 ? <p className="tenue">No hay pendientes.</p> : (
            <ul>{items.map(([a, t]) => <li key={t}><Link to={a}>{t}</Link></li>)}</ul>
          )}
        </div>
      )}
    </div>
  )
}

function useCerrarFuera(ref, cerrar) {
  useEffect(() => {
    const fuera = (e) => { if (ref.current && !ref.current.contains(e.target)) cerrar() }
    const tecla = (e) => { if (e.key === 'Escape') cerrar() }
    document.addEventListener('pointerdown', fuera)
    document.addEventListener('keydown', tecla)
    return () => { document.removeEventListener('pointerdown', fuera); document.removeEventListener('keydown', tecla) }
  }, [ref, cerrar])
}
