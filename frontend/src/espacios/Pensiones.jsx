// Pensiones: cuotas por alumno, descuentos y becas, morosidad y la configuración del cobro (conceptos, montos,
// cronograma, mora y aviso previo). Ver: "pensiones" ver. Configurar, generar y dar descuentos: "pensiones" editar.
import { ArrowLeft, BadgePercent, CalendarClock, FileSpreadsheet, Plus, Receipt, Trash2, Wallet } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, descargar } from '../api.js'
import {
  Buscador, Cifras, Encabezado, fechaCorta, fechaHora, Filtros, Insignia, MenuAcciones, Paginacion, Persona, plural,
  Selector, soles, Tabla, usePaginado,
} from './comun/index.js'
import './configuracion.css'
import './pensiones.css'

export const ESTADO_CUOTA = { pendiente: 'Pendiente', parcial: 'Parcial', pagada: 'Pagada', vencida: 'Vencida', anulada: 'Anulada' }
export const TONO_CUOTA = { pendiente: 'neutro', parcial: 'info', pagada: 'bien', vencida: 'falta', anulada: 'neutro' }
export const MEDIO = { efectivo: 'Efectivo', yape: 'Yape', plin: 'Plin', transferencia: 'Transferencia', tarjeta: 'Tarjeta' }
const TIPO_CONCEPTO = { matricula: 'Matrícula', pension: 'Pensión', otro: 'Otro' }
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Setiembre', 'Octubre',
  'Noviembre', 'Diciembre']

export default function Pensiones({ editar }) {
  return (
    <section className="pensiones">
      <h2 className="solo-lectores">Pensiones</h2>
      <nav className="subpestanas" aria-label="Pensiones">
        <NavLink to="/panel/pensiones" end>Cuotas</NavLink>
        <NavLink to="/panel/pensiones/descuentos">Descuentos y becas</NavLink>
        <NavLink to="/panel/pensiones/morosidad">Morosidad</NavLink>
        <NavLink to="/panel/pensiones/configuracion">Conceptos y cronograma</NavLink>
      </nav>
      <Routes>
        <Route index element={<Alumnos />} />
        <Route path="alumno/:id" element={<DetalleAlumno editar={editar} />} />
        <Route path="descuentos" element={<Descuentos editar={editar} />} />
        <Route path="morosidad" element={<Morosidad />} />
        <Route path="configuracion" element={<Configurar editar={editar} />} />
      </Routes>
    </section>
  )
}

function useSecciones() {
  const [secciones, setSecciones] = useState([])
  useEffect(() => { api('/api/pensiones/secciones').then(setSecciones).catch(() => {}) }, [])
  return secciones
}

// --- Cuotas por alumno ------------------------------------------------------------------------

function Alumnos() {
  const navegar = useNavigate()
  const [q, setQ] = useState('')
  const [estado, setEstado] = useState('')
  const [seccion, setSeccion] = useState('')
  const secciones = useSecciones()
  const { datos, error, cargando, paginacion } = usePaginado('/api/pensiones/alumnos', { q: q.trim(), estado, seccion_id: seccion })
  const columnas = [
    { id: 'alumno', titulo: 'Alumno', ancho: '30%', celda: (a) => (
      <Persona nombre={`${a.apellidos}, ${a.nombres}`} detalle={[a.seccion, !a.activo && 'Retirado'].filter(Boolean).join(' · ')} />) },
    { id: 'total', titulo: 'Total del año', numero: true, ocultarEnCelular: true, celda: (a) => soles(a.total) },
    { id: 'pagado', titulo: 'Pagado', numero: true, celda: (a) => soles(a.pagado) },
    { id: 'saldo', titulo: 'Saldo', numero: true, celda: (a) => soles(a.saldo) },
    { id: 'vencido', titulo: 'Vencido', celda: (a) => (Number(a.vencido) > 0
      ? <Insignia tono="falta">{soles(a.vencido)} · {plural(a.cuotas_vencidas, 'cuota', 'cuotas')}</Insignia>
      : <Insignia tono="bien">Al día</Insignia>) },
  ]
  return (
    <>
      <Encabezado titulo="Cuotas por alumno" descripcion={`Lo que debe y lo que pagó cada alumno${datos ? ` en ${datos.anio}` : ''}.`} />
      <Filtros total={datos && plural(datos.total, 'alumno', 'alumnos')}>
        <Buscador valor={q} cambiar={setQ} placeholder="Buscar por nombre o documento" />
        <Selector etiqueta="Sección" valor={seccion} cambiar={setSeccion}
                  opciones={[['', 'Todas las secciones'], ...secciones.map((s) => [String(s.id), s.nombre])]} />
        <Selector etiqueta="Situación" valor={estado} cambiar={setEstado}
                  opciones={[['', 'Todos'], ['con_deuda_vencida', 'Con deuda vencida'], ['al_dia', 'Al día']]} />
      </Filtros>
      {error && <p className="error">{error}</p>}
      <Tabla etiqueta="Cuotas por alumno" columnas={columnas} filas={datos?.items} cargando={cargando}
             alFila={(a) => navegar(`alumno/${a.id}`)}
             vacio={{ icono: Wallet, titulo: q || estado || seccion ? 'Nadie con esos filtros' : 'Aún no hay cuotas',
               texto: q || estado || seccion ? 'Prueba con otro nombre o quita los filtros.'
                 : 'Arma los conceptos y el cronograma, y genera las cuotas.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

export function TablaCuotas({ cuotas, seleccion, alElegir, etiqueta = 'Cuotas' }) {
  const columnas = [
    { id: 'cuota', titulo: 'Cuota', celda: (c) => {
      const texto = (
        <span className="cuota-texto"><b>{c.concepto} · {c.mes}</b>
          <span className="segunda-linea">{c.anio} · vence el {fechaCorta(c.vence)}</span></span>)
      if (!alElegir || c.estado === 'pagada' || c.estado === 'anulada') return texto
      return (
        <label className="cuota-elegir">
          <input type="checkbox" aria-label={`Cobrar ${c.concepto} ${c.mes}`} checked={seleccion?.[c.id] !== undefined}
                 onChange={(e) => alElegir(c, e.target.checked)} />
          {texto}
        </label>)
    } },
    { id: 'monto', titulo: 'Monto', numero: true, celda: (c) => soles(c.monto) },
    { id: 'descuento', titulo: 'Descuento', numero: true, vacio: (c) => Number(c.descuento) === 0,
      celda: (c) => (Number(c.descuento) ? `− ${soles(c.descuento)}` : '—') },
    { id: 'mora', titulo: 'Mora', numero: true, vacio: (c) => Number(c.mora) === 0,
      celda: (c) => (Number(c.mora) ? soles(c.mora) : '—') },
    { id: 'pagado', titulo: 'Pagado', numero: true, celda: (c) => soles(c.pagado) },
    { id: 'saldo', titulo: 'Saldo', numero: true, celda: (c) => <b>{soles(c.saldo)}</b> },
    { id: 'estado', titulo: 'Estado', celda: (c) => (
      <><Insignia tono={TONO_CUOTA[c.estado]}>{ESTADO_CUOTA[c.estado]}</Insignia>
        {c.dias_atraso > 0 && <span className="segunda-linea">{plural(c.dias_atraso, 'día', 'días')} de atraso</span>}
        {c.anulada_motivo && <span className="segunda-linea">{c.anulada_motivo}</span>}</>) },
  ]
  return <Tabla etiqueta={etiqueta} columnas={columnas} filas={cuotas}
                claseFila={(c) => (c.estado === 'anulada' ? 'atenuada' : '')}
                vacio={{ icono: CalendarClock, titulo: 'Sin cuotas', texto: 'Este alumno aún no tiene cuotas generadas.' }} />
}

export function TablaPagos({ pagos, acciones, etiqueta = 'Pagos' }) {
  const columnas = [
    { id: 'recibo', titulo: 'Recibo', celda: (p) => (
      <><b className="nowrap">{p.recibo}</b><span className="segunda-linea">{fechaHora(p.momento)}</span></>) },
    { id: 'cuotas', titulo: 'Cuotas', ocultarEnCelular: true, celda: (p) => p.cuotas?.join(', ') || p.alumno },
    { id: 'medio', titulo: 'Medio', celda: (p) => (
      <>{MEDIO[p.medio]}{p.numero_operacion && <span className="segunda-linea">Op. {p.numero_operacion}</span>}</>) },
    { id: 'total', titulo: 'Total', numero: true, celda: (p) => <b>{soles(p.total)}</b> },
    { id: 'estado', titulo: 'Estado', celda: (p) => (p.anulado
      ? <><Insignia tono="falta">Anulado</Insignia>{p.anulado_motivo && <span className="segunda-linea">{p.anulado_motivo}</span>}</>
      : <Insignia tono="bien">Válido</Insignia>) },
    acciones && { id: 'acciones', titulo: 'Acciones', acciones: true, celda: (p) => <MenuAcciones etiqueta={p.recibo} {...acciones(p)} /> },
  ].filter(Boolean)
  return <Tabla etiqueta={etiqueta} columnas={columnas} filas={pagos} claseFila={(p) => (p.anulado ? 'atenuada' : '')}
                vacio={{ icono: Receipt, titulo: 'Sin pagos', texto: 'Aún no hay pagos registrados.' }} />
}

function DetalleAlumno({ editar }) {
  const { id } = useParams()
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const [descuento, setDescuento] = useState(false)
  const cargar = useCallback(() => api(`/api/pensiones/alumnos/${id}`).then(setD).catch((e) => setError(e.message)), [id])
  useEffect(() => { cargar() }, [cargar])

  if (error && !d) return <p className="error">{error}</p>
  if (!d) return <p className="tenue">Cargando…</p>
  const vivas = d.cuotas.filter((c) => c.estado !== 'anulada')
  const suma = (lista, campo) => lista.reduce((t, c) => t + Math.round(Number(c[campo]) * 100), 0) / 100
  return (
    <div className="detalle-pensiones">
      <Link to="/panel/pensiones" className="enlace"><ArrowLeft size={18} aria-hidden="true" /> Cuotas por alumno</Link>
      <Encabezado titulo={`${d.apellidos}, ${d.nombres}`} descripcion={d.activo ? null : 'Retirado'}
                  acciones={editar && <button className="boton secundario" onClick={() => setDescuento(true)}>
                    <BadgePercent size={18} aria-hidden="true" /> Dar descuento</button>} />
      <Cifras items={[
        { etiqueta: 'Saldo', valor: soles(suma(vivas, 'saldo').toFixed(2)) },
        { etiqueta: 'Vencido', valor: soles(suma(vivas.filter((c) => c.estado === 'vencida'), 'saldo').toFixed(2)), tono: 'falta' },
        { etiqueta: 'Pagado', valor: soles(suma(vivas, 'pagado').toFixed(2)), tono: 'bien' },
      ]} />
      {descuento && <FormDescuento alumno={d} cerrar={() => setDescuento(false)} alGuardar={() => { setDescuento(false); cargar() }} />}
      <h3>Cuotas</h3>
      <TablaCuotas cuotas={d.cuotas} />
      <h3>Pagos</h3>
      <TablaPagos pagos={d.pagos} acciones={(p) => ({
        principal: { texto: 'Recibo', alHacer: () => descargar(`/api/caja/pagos/${p.id}/recibo.pdf`, `recibo-${p.recibo}.pdf`).catch((e) => setError(e.message)) } })} />
      {d.descuentos.length > 0 && (
        <>
          <h3>Descuentos y becas</h3>
          <ul className="lista">
            {d.descuentos.map((x) => (
              <li key={x.id} className={x.anulado ? 'atenuada' : undefined}>
                <b>{x.tipo === 'porcentaje' ? `${Number(x.valor)} %` : soles(x.valor)}</b> en {x.concepto || 'todos los conceptos'} · {x.motivo}
                <span className="tenue"> · {x.dado_por}, {fechaHora(x.creado_en)}</span>
                {x.anulado && <> <Insignia tono="neutro">Anulado</Insignia></>}
              </li>
            ))}
          </ul>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

// --- Descuentos -----------------------------------------------------------------------------

function FormDescuento({ alumno, cerrar, alGuardar }) {
  const [conceptos, setConceptos] = useState([])
  const [form, setForm] = useState({ concepto_id: '', tipo: 'porcentaje', valor: '', motivo: '' })
  const [error, setError] = useState(null)
  useEffect(() => { api('/api/pensiones/conceptos').then((d) => setConceptos(d.conceptos)).catch(() => {}) }, [])

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    try {
      const r = await api('/api/pensiones/descuentos', { metodo: 'POST', datos: {
        alumno_id: alumno.id, concepto_id: form.concepto_id ? Number(form.concepto_id) : null, tipo: form.tipo,
        valor: form.valor, motivo: form.motivo } })
      alGuardar(r)
    } catch (err) { setError(err.message) }
  }

  return (
    <form className="tarjeta-panel form-pensiones" onSubmit={guardar}>
      <h3>Descuento o beca para {alumno.nombres}</h3>
      <p className="tenue">Se aplica a las cuotas del año que aún no tienen pagos. Entre todos, hasta 100 %.</p>
      <div className="fila-form sin-margen">
        <label>Concepto
          <select value={form.concepto_id} onChange={(e) => setForm({ ...form, concepto_id: e.target.value })}>
            <option value="">Todos los conceptos</option>
            {conceptos.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
        </label>
        <label>Tipo
          <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
            <option value="porcentaje">Porcentaje</option>
            <option value="monto">Monto por cuota (S/)</option>
          </select>
        </label>
        <label>{form.tipo === 'porcentaje' ? 'Porcentaje' : 'Monto (S/)'}
          <input inputMode="decimal" required value={form.valor} pattern="\d+(\.\d{1,2})?"
                 onChange={(e) => setForm({ ...form, valor: e.target.value })} />
        </label>
      </div>
      <label>Motivo
        <input required minLength={3} maxLength={200} value={form.motivo} placeholder="Hermanos, beca por rendimiento…"
               onChange={(e) => setForm({ ...form, motivo: e.target.value })} />
      </label>
      <div className="acciones">
        <button className="boton">Guardar descuento</button>
        <button type="button" className="enlace" onClick={cerrar}>Cancelar</button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

function Descuentos({ editar }) {
  const navegar = useNavigate()
  const [q, setQ] = useState('')
  const [error, setError] = useState(null)
  const { datos, error: errorLista, cargando, recargar, paginacion } = usePaginado('/api/pensiones/descuentos', { q: q.trim() })

  async function anular(x) {
    const motivo = prompt(`¿Por qué se anula el descuento de ${x.alumno}?`)
    if (!motivo) return
    setError(null)
    try { await api(`/api/pensiones/descuentos/${x.id}/anular`, { metodo: 'POST', datos: { motivo } }); recargar() }
    catch (err) { setError(err.message) }
  }

  const columnas = [
    { id: 'alumno', titulo: 'Alumno', ancho: '28%', celda: (x) => <Persona nombre={x.alumno} /> },
    { id: 'descuento', titulo: 'Descuento', celda: (x) => (
      <><b>{x.tipo === 'porcentaje' ? `${Number(x.valor)} %` : soles(x.valor)}</b>
        <span className="segunda-linea">{x.concepto || 'Todos los conceptos'}</span></>) },
    { id: 'motivo', titulo: 'Motivo', celda: (x) => x.motivo },
    { id: 'dado', titulo: 'Lo dio', ocultarEnCelular: true, celda: (x) => (
      <>{x.dado_por}<span className="segunda-linea">{fechaHora(x.creado_en)}</span></>) },
    { id: 'estado', titulo: 'Estado', celda: (x) => (x.anulado
      ? <><Insignia tono="neutro">Anulado</Insignia><span className="segunda-linea">{x.anulado_motivo}</span></>
      : <Insignia tono="bien">Vigente</Insignia>) },
    { id: 'acciones', titulo: 'Acciones', acciones: true, celda: (x) => (
      <MenuAcciones etiqueta={x.alumno} principal={{ texto: 'Ver alumno', alHacer: () => navegar(`/panel/pensiones/alumno/${x.alumno_id}`) }}
                    opciones={editar && !x.anulado ? [{ texto: 'Anular descuento', peligro: true, alHacer: () => anular(x) }] : []} />) },
  ]
  return (
    <>
      <Encabezado titulo="Descuentos y becas" descripcion="Para dar uno nuevo, entra a las cuotas del alumno." />
      <Filtros total={datos && plural(datos.total, 'descuento', 'descuentos')}>
        <Buscador valor={q} cambiar={setQ} placeholder="Buscar por alumno" />
      </Filtros>
      {(error || errorLista) && <p className="error">{error || errorLista}</p>}
      <Tabla etiqueta="Descuentos y becas" columnas={columnas} filas={datos?.items} cargando={cargando}
             claseFila={(x) => (x.anulado ? 'atenuada' : '')}
             vacio={{ icono: BadgePercent, titulo: q ? 'Nadie con ese nombre' : 'Sin descuentos', texto: q ? 'Prueba con otro nombre.'
               : 'Los descuentos y becas se dan desde las cuotas de cada alumno.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

// --- Morosidad --------------------------------------------------------------------------------

function Morosidad() {
  const navegar = useNavigate()
  const [seccion, setSeccion] = useState('')
  const [error, setError] = useState(null)
  const secciones = useSecciones()
  const { datos, error: errorLista, cargando, paginacion } = usePaginado('/api/pensiones/morosidad', { seccion_id: seccion })
  const columnas = [
    { id: 'alumno', titulo: 'Alumno', ancho: '32%', celda: (f) => (
      <Persona nombre={f.alumno} detalle={[f.seccion, !f.activo && 'Retirado'].filter(Boolean).join(' · ')} />) },
    { id: 'cuotas', titulo: 'Cuotas vencidas', numero: true, celda: (f) => f.cuotas },
    { id: 'monto', titulo: 'Monto', numero: true, celda: (f) => <b>{soles(f.monto)}</b> },
    { id: 'dias', titulo: 'Días de atraso', numero: true, celda: (f) => (
      <Insignia tono={f.dias > 60 ? 'falta' : 'tarde'}>{plural(f.dias, 'día', 'días')}</Insignia>) },
  ]
  const excel = () => descargar(`/api/pensiones/morosidad.xlsx${seccion ? `?seccion_id=${seccion}` : ''}`, 'morosidad.xlsx')
    .catch((e) => setError(e.message))
  return (
    <>
      <Encabezado titulo="Morosidad" descripcion="Alumnos con cuotas vencidas sin pagar, por sección. La deuda no bloquea la asistencia ni la app de la familia."
                  acciones={<button className="boton secundario" onClick={excel}><FileSpreadsheet size={18} aria-hidden="true" /> Excel</button>} />
      {datos && <Cifras items={[{ etiqueta: 'Deuda vencida', valor: soles(datos.monto_total), tono: 'falta' },
        { etiqueta: 'Alumnos morosos', valor: datos.total }]} />}
      <Filtros total={datos && plural(datos.total, 'alumno', 'alumnos')}>
        <Selector etiqueta="Sección" valor={seccion} cambiar={setSeccion}
                  opciones={[['', 'Todas las secciones'], ...secciones.map((s) => [String(s.id), s.nombre])]} />
      </Filtros>
      {(error || errorLista) && <p className="error">{error || errorLista}</p>}
      <Tabla etiqueta="Morosidad" columnas={columnas} filas={datos?.items} cargando={cargando} clave={(f) => f.alumno_id}
             alFila={(f) => navegar(`/panel/pensiones/alumno/${f.alumno_id}`)}
             vacio={{ icono: Wallet, titulo: 'Nadie con deuda vencida', texto: 'Todos los alumnos están al día.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

// --- Configuración: mora, aviso previo, conceptos, montos y cronograma ------------------------

function Configurar({ editar }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const [mensaje, setMensaje] = useState(null)
  const [nuevo, setNuevo] = useState(null)
  const cargar = useCallback(() => api('/api/pensiones/conceptos').then(setD).catch((e) => setError(e.message)), [])
  useEffect(() => { cargar() }, [cargar])

  async function llamar(fn, ok) {
    setError(null)
    setMensaje(null)
    try { const r = await fn(); if (ok) setMensaje(ok); await cargar(); return r } catch (err) { setError(err.message); return null }
  }

  async function generar() {
    const r = await llamar(() => api('/api/pensiones/generar', { metodo: 'POST' }))
    if (r) setMensaje(`${plural(r.creadas, 'cuota nueva', 'cuotas nuevas')}${r.sin_monto ? ` · ${plural(r.sin_monto, 'alumno', 'alumnos')} sin monto para su grado o nivel` : ''}.`)
  }

  async function crear(e) {
    e.preventDefault()
    if (await llamar(() => api('/api/pensiones/conceptos', { metodo: 'POST', datos: { ...nuevo, igv: nuevo.igv || null } }), 'Concepto creado')) setNuevo(null)
  }

  if (!d) return error ? <p className="error">{error}</p> : <p className="tenue">Cargando…</p>
  return (
    <>
      <Encabezado titulo={`Conceptos y cronograma ${d.anio.anio}`}
                  descripcion={`Año escolar del ${fechaCorta(d.anio.inicio)} al ${fechaCorta(d.anio.fin)}. Generar crea solo las cuotas que faltan (alumnos nuevos); no duplica.`}
                  acciones={editar && (
                    <>
                      <button className="boton secundario" onClick={() => setNuevo({ nombre: '', tipo: 'pension', igv: '' })}>
                        <Plus size={18} aria-hidden="true" /> Concepto</button>
                      <button className="boton" onClick={generar}>Generar cuotas</button>
                    </>)} />
      {mensaje && <p className="tenue" role="status">{mensaje}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {nuevo && (
        <form className="tarjeta-panel form-pensiones" onSubmit={crear}>
          <h3>Nuevo concepto</h3>
          <div className="fila-form sin-margen">
            <label>Nombre<input required maxLength={80} value={nuevo.nombre} placeholder="Pensión, Matrícula, Uniforme…"
                                onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} /></label>
            <label>Tipo
              <select value={nuevo.tipo} onChange={(e) => setNuevo({ ...nuevo, tipo: e.target.value })}>
                {Object.entries(TIPO_CONCEPTO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>IGV
              <select value={nuevo.igv} onChange={(e) => setNuevo({ ...nuevo, igv: e.target.value })}>
                <option value="">{nuevo.tipo === 'otro' ? 'Gravado (por defecto)' : 'Inafecto (por defecto)'}</option>
                <option value="inafecto">Inafecto</option>
                <option value="gravado">Gravado</option>
              </select>
            </label>
          </div>
          <p className="tenue">Matrícula y pensión van inafectas por defecto (Ley del IGV, art. 2, inciso g); uniformes, útiles o cafetería, gravados. Confírmalo con tu contador.</p>
          <div className="acciones">
            <button className="boton">Crear</button>
            <button type="button" className="enlace" onClick={() => setNuevo(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {d.conceptos.length === 0 && !nuevo && (
        <div className="vacio"><span className="vacio-icono"><Wallet size={32} aria-hidden="true" /></span>
          <h3>Aún no hay conceptos</h3><p className="tenue">Por ejemplo: Matrícula y Pensión (10 cuotas de marzo a diciembre).</p></div>
      )}
      {d.conceptos.map((c) => <Concepto key={c.id} c={c} niveles={d.niveles} anio={d.anio} editar={editar} llamar={llamar} />)}
      <ConfigMora editar={editar} />
    </>
  )
}

function Concepto({ c, niveles, anio, editar, llamar }) {
  const [montos, setMontos] = useState(null)
  const [serie, setSerie] = useState(null)
  const [linea, setLinea] = useState(null)

  function editarMontos() {
    const m = {}
    for (const x of c.montos) m[x.grado_id ? `g${x.grado_id}` : `n${x.nivel_id}`] = x.monto
    setMontos(m)
  }

  async function guardarMontos(e) {
    e.preventDefault()
    const lista = Object.entries(montos).filter(([, v]) => v !== '' && v != null)
      .map(([k, v]) => ({ [k[0] === 'g' ? 'grado_id' : 'nivel_id']: Number(k.slice(1)), monto: v }))
    if (await llamar(() => api(`/api/pensiones/conceptos/${c.id}/montos`, { metodo: 'PUT', datos: { montos: lista } }), 'Montos guardados')) setMontos(null)
  }

  async function guardarSerie(e) {
    e.preventDefault()
    if (await llamar(() => api(`/api/pensiones/conceptos/${c.id}/cronograma/serie`, { metodo: 'POST', datos: {
      desde: Number(serie.desde), hasta: Number(serie.hasta), dia: Number(serie.dia) } }), 'Cronograma armado')) setSerie(null)
  }

  async function guardarLinea(e) {
    e.preventDefault()
    const datos = { numero: Number(linea.numero), mes: linea.mes, vence: linea.vence }
    const r = linea.id
      ? await llamar(() => api(`/api/pensiones/cronograma/${linea.id}`, { metodo: 'PUT', datos }), 'Cuota actualizada')
      : await llamar(() => api(`/api/pensiones/conceptos/${c.id}/cronograma`, { metodo: 'POST', datos }), 'Cuota agregada')
    if (r) setLinea(null)
  }

  async function borrarLinea(x) {
    if (confirm(`¿Quitar la cuota ${x.numero} (${x.mes}) del cronograma?`)) {
      await llamar(() => api(`/api/pensiones/cronograma/${x.id}`, { metodo: 'DELETE' }), 'Cuota quitada')
    }
  }

  async function cambiarActivo() {
    await llamar(() => api(`/api/pensiones/conceptos/${c.id}`, { metodo: 'PUT', datos: { nombre: c.nombre, tipo: c.tipo, igv: c.igv, activo: !c.activo } }),
      c.activo ? 'Concepto desactivado' : 'Concepto activado')
  }

  async function borrar() {
    if (confirm(`¿Borrar el concepto «${c.nombre}»?`)) await llamar(() => api(`/api/pensiones/conceptos/${c.id}`, { metodo: 'DELETE' }), 'Concepto borrado')
  }

  const nombreMonto = (x) => {
    for (const n of niveles) {
      if (x.nivel_id === n.id) return n.nombre
      const g = n.grados.find((gr) => gr.id === x.grado_id)
      if (g) return `${n.nombre} · ${g.nombre}`
    }
    return ''
  }

  return (
    <article className="tarjeta-panel concepto">
      <header className="concepto-cabeza">
        <div>
          <h3>{c.nombre} {!c.activo && <Insignia tono="neutro">Desactivado</Insignia>}</h3>
          <span className="tenue">{TIPO_CONCEPTO[c.tipo]} · {c.igv === 'inafecto' ? 'Inafecto al IGV' : 'Gravado con IGV'}
            {c.cuotas_generadas > 0 && ` · ${plural(c.cuotas_generadas, 'cuota generada', 'cuotas generadas')}`}</span>
        </div>
        {editar && (
          <MenuAcciones etiqueta={c.nombre} principal={{ texto: 'Montos', alHacer: editarMontos }}
                        opciones={[{ texto: c.activo ? 'Desactivar' : 'Activar', alHacer: cambiarActivo },
                          c.cuotas_generadas === 0 && { texto: 'Borrar concepto', peligro: true, icono: Trash2, alHacer: borrar }]} />
        )}
      </header>
      <div className="concepto-cuerpo">
        <div>
          <h4>Montos</h4>
          {c.montos.length === 0 ? <p className="tenue">Sin montos: no se generan cuotas.</p> : (
            <ul className="lista-montos">{c.montos.map((x) => <li key={x.id}><span>{nombreMonto(x)}</span><b>{soles(x.monto)}</b></li>)}</ul>
          )}
        </div>
        <div>
          <h4>Cronograma</h4>
          {c.cronograma.length === 0 ? <p className="tenue">Sin cuotas en el cronograma.</p> : (
            <ul className="lista-montos">{c.cronograma.map((x) => (
              <li key={x.id}>
                <span>{x.numero}. {x.mes}</span>
                <span className="tenue">vence {fechaCorta(x.vence)}</span>
                {editar && (
                  <span className="nowrap">
                    <button className="enlace-chico enlace" onClick={() => setLinea(x)}>Editar</button>
                    {c.cuotas_generadas === 0 && <button className="enlace-chico enlace" onClick={() => borrarLinea(x)}>Quitar</button>}
                  </span>
                )}
              </li>))}</ul>
          )}
          {editar && (
            <div className="acciones">
              <button className="boton secundario chico" onClick={() => setSerie({ desde: 3, hasta: 12, dia: 31 })}>Armar por meses</button>
              <button className="enlace" onClick={() => setLinea({ numero: c.cronograma.length + 1, mes: '', vence: anio.inicio })}>Agregar una cuota</button>
            </div>
          )}
        </div>
      </div>
      {montos && (
        <form className="form-pensiones" onSubmit={guardarMontos}>
          <p className="tenue">El monto del grado manda sobre el del nivel. Deja vacío lo que no aplica. Las cuotas ya generadas no cambian.</p>
          {niveles.map((n) => (
            <fieldset key={n.id} className="montos-nivel">
              <legend>{n.nombre}</legend>
              <label>Todo el nivel (S/)
                <input inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={montos[`n${n.id}`] ?? ''}
                       onChange={(e) => setMontos({ ...montos, [`n${n.id}`]: e.target.value })} />
              </label>
              {n.grados.map((g) => (
                <label key={g.id}>{g.nombre} (S/)
                  <input inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={montos[`g${g.id}`] ?? ''} placeholder="Del nivel"
                         onChange={(e) => setMontos({ ...montos, [`g${g.id}`]: e.target.value })} />
                </label>
              ))}
            </fieldset>
          ))}
          <div className="acciones">
            <button className="boton">Guardar montos</button>
            <button type="button" className="enlace" onClick={() => setMontos(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {serie && (
        <form className="form-pensiones" onSubmit={guardarSerie}>
          <div className="fila-form sin-margen">
            <label>Desde
              <select value={serie.desde} onChange={(e) => setSerie({ ...serie, desde: e.target.value })}>
                {MESES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
              </select>
            </label>
            <label>Hasta
              <select value={serie.hasta} onChange={(e) => setSerie({ ...serie, hasta: e.target.value })}>
                {MESES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
              </select>
            </label>
            <label>Vence el día
              <input type="number" min={1} max={31} required value={serie.dia} onChange={(e) => setSerie({ ...serie, dia: e.target.value })} />
            </label>
          </div>
          <p className="tenue">Si el mes no tiene ese día, vence el último del mes. El vencimiento va desde 3 meses antes del inicio de clases hasta el fin del año escolar.</p>
          <div className="acciones">
            <button className="boton">Armar cronograma</button>
            <button type="button" className="enlace" onClick={() => setSerie(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {linea && (
        <form className="form-pensiones" onSubmit={guardarLinea}>
          <div className="fila-form sin-margen">
            <label>N.°<input type="number" min={1} max={24} required value={linea.numero} onChange={(e) => setLinea({ ...linea, numero: e.target.value })} /></label>
            <label>Mes<input required maxLength={20} value={linea.mes} placeholder="Marzo" onChange={(e) => setLinea({ ...linea, mes: e.target.value })} /></label>
            <label>Vence<input type="date" required min={anio.vence_desde} max={anio.fin} value={linea.vence}
                               onChange={(e) => setLinea({ ...linea, vence: e.target.value })} /></label>
          </div>
          {linea.id && c.cuotas_generadas > 0 && <p className="tenue">El nuevo vencimiento vale también para las cuotas ya generadas.</p>}
          <div className="acciones">
            <button className="boton">Guardar</button>
            <button type="button" className="enlace" onClick={() => setLinea(null)}>Cancelar</button>
          </div>
        </form>
      )}
    </article>
  )
}

function ConfigMora({ editar }) {
  const [cfg, setCfg] = useState(null)
  const [mensaje, setMensaje] = useState(null)
  useEffect(() => { api('/api/pensiones/config').then((c) => setCfg({ ...c, mora_tope: c.mora_tope || '' })).catch(() => {}) }, [])

  async function guardar(e) {
    e.preventDefault()
    setMensaje(null)
    try {
      const r = await api('/api/pensiones/config', { metodo: 'PUT', datos: {
        mora_tipo: cfg.mora_tipo, mora_valor: cfg.mora_tipo === 'ninguna' ? '0' : cfg.mora_valor,
        mora_tope: cfg.mora_tipo === 'ninguna' || cfg.mora_tope === '' ? null : cfg.mora_tope,
        dias_aviso_previo: Number(cfg.dias_aviso_previo) } })
      setCfg({ ...r, mora_tope: r.mora_tope || '' })
      setMensaje({ texto: 'Cambios guardados' })
    } catch (err) { setMensaje({ texto: err.message, error: true }) }
  }

  if (!cfg) return null
  return (
    <form className="tarjeta-panel form-pensiones" onSubmit={guardar}>
      <fieldset disabled={!editar} className="sin-borde">
        <h3>Mora y recordatorios</h3>
        <div className="fila-form sin-margen">
          <label>Mora
            <select value={cfg.mora_tipo} onChange={(e) => setCfg({ ...cfg, mora_tipo: e.target.value })}>
              <option value="ninguna">Sin mora</option>
              <option value="fijo">Monto fijo por cuota vencida</option>
              <option value="porcentaje">Porcentaje mensual sobre la cuota</option>
            </select>
          </label>
          {cfg.mora_tipo !== 'ninguna' && (
            <>
              <label>{cfg.mora_tipo === 'fijo' ? 'Monto (S/)' : 'Porcentaje al mes'}
                <input inputMode="decimal" required pattern="\d+(\.\d{1,2})?" value={cfg.mora_valor}
                       onChange={(e) => setCfg({ ...cfg, mora_valor: e.target.value })} />
              </label>
              <label>Tope por cuota (S/)
                <input inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={cfg.mora_tope} placeholder="Sin tope"
                       onChange={(e) => setCfg({ ...cfg, mora_tope: e.target.value })} />
              </label>
            </>
          )}
          <label>Recordatorio, días antes
            <input type="number" min={0} max={30} required value={cfg.dias_aviso_previo}
                   onChange={(e) => setCfg({ ...cfg, dias_aviso_previo: e.target.value })} />
          </label>
        </div>
        {cfg.mora_tipo !== 'ninguna' && <p className="aviso">{cfg.aviso_mora} Sin interés sobre interés: el porcentaje se calcula siempre sobre la cuota.</p>}
        <p className="tenue">El recordatorio llega por la app al responsable de pago, junta todas sus cuotas en un solo aviso, y otro el día que vence. Respeta el horario sin molestar. Se apaga en Configuración › Avisos.</p>
        {editar && <div className="acciones"><button className="boton">Guardar</button></div>}
      </fieldset>
      {mensaje && <p className={mensaje.error ? 'error' : 'tenue'} role="status">{mensaje.texto}</p>}
    </form>
  )
}
