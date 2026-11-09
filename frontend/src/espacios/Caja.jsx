// Caja: cobrar con la caja del día abierta, pagos y recibos, cierre de cajas, gastos y reportes de ingresos.
// Ver: "caja" ver. Abrir caja, cobrar, anular y registrar gastos: "caja" editar. Anular con la caja cerrada
// o un gasto de otro día: director o rol con "puede anular" (el backend decide).
// Comprobantes electrónicos (si el colegio emite): boleta al responsable de pago o factura con RUC; salen en
// segundo plano. "Comprobantes" lista los rechazados y los que fallaron 5 veces ("Reintentar": caja editar).
import { ArrowLeft, FileSpreadsheet, FileWarning, Lock, Paperclip, Plus, Receipt, RotateCw, Search, Wallet } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, descargar } from '../api.js'
import {
  Buscador, Cifras, Encabezado, fechaCorta, fechaHora, Filtros, Insignia, MenuAcciones, Paginacion, Persona, plural,
  Selector, soles, Tabla, usePaginado,
} from './comun/index.js'
import { MEDIO, TablaCuotas } from './Pensiones.jsx'
import './configuracion.css'
import './pensiones.css'

const MEDIOS = Object.entries(MEDIO)
const centimos = (v) => Math.round(Number(v || 0) * 100)
const aSoles = (c) => (c / 100).toFixed(2)
const hoyLima = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date())
const primeroDeMes = () => `${hoyLima().slice(0, 8)}01`
const reciboPdf = (p) => descargar(`/api/caja/pagos/${p.id}/recibo.pdf`, `recibo-${p.recibo}.pdf`)
const TIPO_COMPROBANTE = { boleta: 'Boleta', factura: 'Factura' }
const ESTADO_COMPROBANTE = {
  pendiente: ['Por enviar', 'neutro'], enviado: ['Enviado', 'info'], aceptado: ['Aceptado', 'bien'],
  rechazado: ['Rechazado', 'falta'], anulado: ['Anulado', 'neutro'],
}

function EstadoComprobante({ c }) {
  const [texto, tono] = ESTADO_COMPROBANTE[c.estado] || [c.estado, 'neutro']
  return <Insignia tono={tono}>{texto}</Insignia>
}

export default function Caja({ editar }) {
  return (
    <section className="pensiones">
      <h2 className="solo-lectores">Caja</h2>
      <nav className="subpestanas" aria-label="Caja">
        {editar && <NavLink to="/panel/caja" end>Cobrar</NavLink>}
        <NavLink to={editar ? '/panel/caja/pagos' : '/panel/caja'} end={!editar}>Pagos</NavLink>
        <NavLink to="/panel/caja/cajas">Cierres de caja</NavLink>
        <NavLink to="/panel/caja/gastos">Gastos</NavLink>
        <NavLink to="/panel/caja/reportes">Reportes</NavLink>
        <NavLink to="/panel/caja/comprobantes">Comprobantes</NavLink>
      </nav>
      <Routes>
        <Route index element={editar ? <Cobrar /> : <Pagos editar={false} />} />
        <Route path="pagos" element={<Pagos editar={editar} />} />
        <Route path="cajas" element={<Cajas />} />
        <Route path="gastos" element={<Gastos editar={editar} />} />
        <Route path="reportes" element={<Reportes />} />
        <Route path="comprobantes" element={<ComprobantesConError editar={editar} />} />
      </Routes>
    </section>
  )
}

// --- Cobrar ---------------------------------------------------------------------------------

function Cobrar() {
  const [estado, setEstado] = useState(null)
  const [error, setError] = useState(null)
  const [alumno, setAlumno] = useState(null)
  const [recibo, setRecibo] = useState(null)
  const cargar = useCallback(() => api('/api/caja/mi-caja').then(setEstado).catch((e) => setError(e.message)), [])
  useEffect(() => { cargar() }, [cargar])

  async function abrir() {
    setError(null)
    try { await api('/api/caja/abrir', { metodo: 'POST' }); cargar() } catch (err) { setError(err.message) }
  }

  if (!estado) return error ? <p className="error">{error}</p> : <p className="tenue">Cargando…</p>
  const caja = estado.caja
  if (!caja) {
    return (
      <>
        <Encabezado titulo="Cobrar" descripcion="Para cobrar, abre tu caja del día. Al terminar la jornada la cierras con el efectivo contado." />
        <div className="vacio">
          <span className="vacio-icono"><Wallet size={32} aria-hidden="true" /></span>
          <h3>Tu caja está cerrada</h3>
          <p className="tenue">Hoy es {fechaCorta(estado.hoy)}.</p>
          <button className="boton" onClick={abrir}>Abrir mi caja</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </>
    )
  }
  const deOtroDia = caja.fecha !== estado.hoy
  return (
    <>
      <Encabezado titulo="Cobrar" descripcion={`Tu caja del ${fechaCorta(caja.fecha)}, abierta ${fechaHora(caja.abierta_en)}.`} />
      <ResumenCaja caja={caja} alCerrar={() => { setAlumno(null); setRecibo(null); cargar() }} />
      {deOtroDia ? (
        <p className="aviso" role="alert">Esta caja es de otro día. Ciérrala con el efectivo contado y abre la de hoy para seguir cobrando.</p>
      ) : (
        <>
          {recibo && <ReciboListo pago={recibo} cerrar={() => setRecibo(null)} />}
          {alumno
            ? <CobrarAlumno id={alumno} comprobantes={estado.comprobantes} volver={() => setAlumno(null)}
                            alCobrar={(p) => { setRecibo(p); setAlumno(null); cargar() }} />
            : <BuscarAlumno elegir={(id) => { setRecibo(null); setAlumno(id) }} />}
        </>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </>
  )
}

function ResumenCaja({ caja, alCerrar }) {
  const [cierre, setCierre] = useState(null)
  const [error, setError] = useState(null)

  async function cerrar(e) {
    e.preventDefault()
    setError(null)
    try {
      await api('/api/caja/cerrar', { metodo: 'POST', datos: { contado: cierre } })
      setCierre(null)
      alCerrar()
    } catch (err) { setError(err.message) }
  }

  const diferencia = cierre === null || cierre === '' ? null : centimos(cierre) - centimos(caja.totales.efectivo)
  return (
    <div className="tarjeta-panel caja-resumen">
      <Cifras items={[
        { etiqueta: 'Cobrado', valor: soles(caja.total), tono: 'bien' },
        { etiqueta: 'Efectivo', valor: soles(caja.totales.efectivo) },
        { etiqueta: 'Otros medios', valor: soles(aSoles(centimos(caja.total) - centimos(caja.totales.efectivo))) },
        { etiqueta: 'Pagos', valor: caja.pagos },
      ]} />
      {cierre === null ? (
        <div className="acciones">
          <button className="boton secundario" onClick={() => setCierre('')}><Lock size={18} aria-hidden="true" /> Cerrar caja</button>
        </div>
      ) : (
        <form onSubmit={cerrar} className="form-pensiones">
          <ul className="lista-montos">
            {MEDIOS.map(([m, t]) => <li key={m}><span>{t}</span><b>{soles(caja.totales[m])}</b></li>)}
          </ul>
          <label>Efectivo contado (S/)
            <input inputMode="decimal" required pattern="\d+(\.\d{1,2})?" autoFocus value={cierre}
                   onChange={(e) => setCierre(e.target.value)} />
          </label>
          {diferencia !== null && (
            <p className={diferencia === 0 ? 'tenue' : 'aviso'}>
              {diferencia === 0 ? 'Cuadra con el efectivo cobrado.'
                : `${diferencia > 0 ? 'Sobran' : 'Faltan'} ${soles(aSoles(Math.abs(diferencia)))} frente al efectivo cobrado.`}
            </p>
          )}
          <p className="tenue">Cerrada, ya no admite cobros ni anulaciones tuyas: solo el director o un rol con permiso para anular podrán anular.</p>
          <div className="acciones">
            <button className="boton">Cerrar caja</button>
            <button type="button" className="enlace" onClick={() => setCierre(null)}>Cancelar</button>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      )}
    </div>
  )
}

function BuscarAlumno({ elegir }) {
  const [q, setQ] = useState('')
  const [lista, setLista] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    const texto = q.trim()
    if (texto.length < 2) { setLista(null); return undefined }
    const t = setTimeout(() => {
      api(`/api/caja/alumnos?q=${encodeURIComponent(texto)}`).then(setLista).catch((e) => setError(e.message))
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div className="tarjeta-panel">
      <h3>¿A quién cobras?</h3>
      <Filtros>
        <Buscador valor={q} cambiar={setQ} placeholder="Apellido, nombre o documento del alumno" />
      </Filtros>
      {error && <p className="error">{error}</p>}
      {lista && lista.length === 0 && <p className="tenue">Nadie con ese nombre o documento.</p>}
      {lista && lista.length > 0 && (
        <ul className="lista-alumnos">
          {lista.map((a) => (
            <li key={a.id}>
              <button type="button" className="fila-alumno" onClick={() => elegir(a.id)}>
                <Persona nombre={`${a.apellidos}, ${a.nombres}`}
                         detalle={[a.seccion, a.numero_documento, !a.activo && 'Retirado'].filter(Boolean).join(' · ')} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {!lista && <p className="tenue"><Search size={16} aria-hidden="true" /> Escribe al menos 2 letras.</p>}
    </div>
  )
}

function CobrarAlumno({ id, comprobantes, volver, alCobrar }) {
  const [a, setA] = useState(null)
  const [factura, setFactura] = useState(null) // null: boleta; { ruc, razon_social }: factura
  const [montos, setMontos] = useState({})
  const [medio, setMedio] = useState('efectivo')
  const [operacion, setOperacion] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  useEffect(() => { api(`/api/caja/alumnos/${id}`).then(setA).catch((e) => setError(e.message)) }, [id])

  const pendientes = useMemo(() => (a ? a.cuotas.filter((c) => c.estado !== 'pagada' && c.estado !== 'anulada') : []), [a])
  const total = Object.values(montos).reduce((t, v) => t + centimos(v), 0)

  function elegirCuota(c, si) {
    const nuevos = { ...montos }
    if (si) nuevos[c.id] = c.saldo
    else delete nuevos[c.id]
    setMontos(nuevos)
  }

  async function cobrar(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      const p = await api('/api/caja/pagos', { metodo: 'POST', datos: {
        alumno_id: a.id, medio, numero_operacion: medio === 'efectivo' ? null : operacion.trim(),
        detalles: Object.entries(montos).map(([cuota, monto]) => ({ cuota_id: Number(cuota), monto })),
        factura: factura && { ruc: factura.ruc.trim(), razon_social: factura.razon_social } } })
      alCobrar(p)
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  if (!a) return error ? <p className="error">{error}</p> : <p className="tenue">Cargando…</p>
  const elegidas = pendientes.filter((c) => montos[c.id] !== undefined)
  return (
    <div className="tarjeta-panel cobrar">
      <button type="button" className="enlace" onClick={volver}><ArrowLeft size={18} aria-hidden="true" /> Otro alumno</button>
      <h3>{a.apellidos}, {a.nombres}</h3>
      {!a.activo && <p className="tenue">Retirado: puede pagar lo que quedó pendiente.</p>}
      {pendientes.length === 0 ? <p className="tenue">No tiene cuotas por pagar.</p> : (
        <form onSubmit={cobrar} className="form-pensiones">
          <p className="tenue">Marca las cuotas que paga. Puedes cobrar menos que el saldo (pago parcial), nunca más.</p>
          <TablaCuotas cuotas={pendientes} seleccion={montos} alElegir={elegirCuota} etiqueta="Cuotas por pagar" />
          {elegidas.length > 0 && (
            <>
              <fieldset className="montos-cobro">
                <legend>Monto que paga</legend>
                {elegidas.map((c) => (
                  <label key={c.id}>{c.concepto} · {c.mes} <span className="tenue">(saldo {soles(c.saldo)})</span>
                    <input inputMode="decimal" required pattern="\d+(\.\d{1,2})?" value={montos[c.id]}
                           onChange={(e) => setMontos({ ...montos, [c.id]: e.target.value })} />
                  </label>
                ))}
              </fieldset>
              <div className="fila-form sin-margen">
                <label>Medio de pago
                  <select value={medio} onChange={(e) => setMedio(e.target.value)}>
                    {MEDIOS.map(([m, t]) => <option key={m} value={m}>{t}</option>)}
                  </select>
                </label>
                {medio !== 'efectivo' && (
                  <label>N.° de operación
                    <input required maxLength={40} value={operacion} onChange={(e) => setOperacion(e.target.value)} />
                  </label>
                )}
              </div>
              {comprobantes && (
                <fieldset className="montos-cobro">
                  <legend>Comprobante electrónico</legend>
                  <div className="fila-form sin-margen">
                    <label>Tipo
                      <select value={factura ? 'factura' : 'boleta'}
                              onChange={(e) => setFactura(e.target.value === 'factura' ? { ruc: '', razon_social: '' } : null)}>
                        <option value="boleta">Boleta al responsable de pago</option>
                        <option value="factura">Factura</option>
                      </select>
                    </label>
                    {factura && (
                      <>
                        <label>RUC
                          <input required inputMode="numeric" pattern="\d{11}" maxLength={11} value={factura.ruc}
                                 onChange={(e) => setFactura({ ...factura, ruc: e.target.value })} />
                        </label>
                        <label>Razón social
                          <input required maxLength={200} value={factura.razon_social}
                                 onChange={(e) => setFactura({ ...factura, razon_social: e.target.value })} />
                        </label>
                      </>
                    )}
                  </div>
                  <p className="tenue">Se envía en segundo plano; el recibo interno se entrega igual.</p>
                </fieldset>
              )}
              <div className="cobrar-total">
                <span>Total</span><b>{soles(aSoles(total))}</b>
              </div>
              <div className="acciones">
                <button className="boton" disabled={enviando || total <= 0}>Cobrar {soles(aSoles(total))}</button>
              </div>
            </>
          )}
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      )}
    </div>
  )
}

function ReciboListo({ pago, cerrar }) {
  const [error, setError] = useState(null)
  return (
    <div className="tarjeta-panel recibo-listo" role="status">
      <div>
        <b>Recibo {pago.recibo} · {soles(pago.total)}</b>
        <span className="tenue"> {pago.alumno} · {MEDIO[pago.medio]}</span>
        {pago.comprobante && (
          <span className="segunda-linea">{TIPO_COMPROBANTE[pago.comprobante.tipo]} {pago.comprobante.numero} a
            {' '}{pago.comprobante.cliente}: se envía en segundo plano.</span>
        )}
      </div>
      <div className="acciones">
        <button className="boton" onClick={() => reciboPdf(pago).catch((e) => setError(e.message))}>
          <Receipt size={18} aria-hidden="true" /> Descargar recibo</button>
        <button className="enlace" onClick={cerrar}>Listo</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

// --- Pagos ----------------------------------------------------------------------------------

function Pagos({ editar }) {
  const [filtros, setFiltros] = useState({ q: '', medio: '', estado: '', cajero_id: '', desde: primeroDeMes(), hasta: hoyLima() })
  const [error, setError] = useState(null)
  const { datos, error: errorLista, cargando, recargar, paginacion } = usePaginado('/api/caja/pagos', { ...filtros, q: filtros.q.trim() })
  const cambiar = (k) => (v) => setFiltros({ ...filtros, [k]: v })

  async function anular(p) {
    const motivo = prompt(`¿Por qué se anula el recibo ${p.recibo} de ${p.alumno}? Las cuotas recuperan su saldo.`)
    if (!motivo) return
    setError(null)
    try { await api(`/api/caja/pagos/${p.id}/anular`, { metodo: 'POST', datos: { motivo } }); recargar() }
    catch (err) { setError(err.message) }
  }

  const columnas = [
    { id: 'recibo', titulo: 'Recibo', celda: (p) => (
      <><b className="nowrap">{p.recibo}</b><span className="segunda-linea">{fechaHora(p.momento)}</span></>) },
    { id: 'alumno', titulo: 'Alumno', ancho: '26%', celda: (p) => p.alumno },
    { id: 'medio', titulo: 'Medio', celda: (p) => (
      <>{MEDIO[p.medio]}{p.numero_operacion && <span className="segunda-linea">Op. {p.numero_operacion}</span>}</>) },
    { id: 'comprobante', titulo: 'Comprobante', ocultarEnCelular: true, celda: (p) => (p.comprobante ? (
      <><span className="nowrap">{p.comprobante.numero}</span><span className="segunda-linea"><EstadoComprobante c={p.comprobante} /></span></>
    ) : <span className="tenue">Solo recibo</span>) },
    { id: 'cajero', titulo: 'Cajero', ocultarEnCelular: true, celda: (p) => p.cajero },
    { id: 'total', titulo: 'Total', numero: true, celda: (p) => <b>{soles(p.total)}</b> },
    { id: 'estado', titulo: 'Estado', celda: (p) => (p.anulado ? <Insignia tono="falta">Anulado</Insignia> : <Insignia tono="bien">Válido</Insignia>) },
    { id: 'acciones', titulo: 'Acciones', acciones: true, celda: (p) => (
      <MenuAcciones etiqueta={p.recibo} principal={{ texto: 'Recibo', alHacer: () => reciboPdf(p).catch((e) => setError(e.message)) }}
                    opciones={editar && !p.anulado ? [{ texto: 'Anular pago', peligro: true, alHacer: () => anular(p) }] : []} />) },
  ]
  return (
    <>
      <Encabezado titulo="Pagos" descripcion="Nada se borra: un pago anulado queda visible con su motivo. Con la caja abierta lo anula quien cobró; con la caja cerrada, el director o un rol con permiso para anular." />
      {datos && <Cifras items={[{ etiqueta: 'Cobrado (válidos)', valor: soles(datos.suma), tono: 'bien' }]} />}
      <Filtros total={datos && plural(datos.total, 'pago', 'pagos')}>
        <Buscador valor={filtros.q} cambiar={cambiar('q')} placeholder="Alumno, documento u operación" />
        <label className="selector"><span className="solo-lectores">Desde</span>
          <input type="date" aria-label="Desde" value={filtros.desde} onChange={(e) => cambiar('desde')(e.target.value)} /></label>
        <label className="selector"><span className="solo-lectores">Hasta</span>
          <input type="date" aria-label="Hasta" value={filtros.hasta} onChange={(e) => cambiar('hasta')(e.target.value)} /></label>
        <Selector etiqueta="Medio" valor={filtros.medio} cambiar={cambiar('medio')} opciones={[['', 'Todos los medios'], ...MEDIOS]} />
        <Selector etiqueta="Cajero" valor={filtros.cajero_id} cambiar={cambiar('cajero_id')}
                  opciones={[['', 'Todos los cajeros'], ...(datos?.cajeros || []).map((c) => [String(c.id), c.nombre])]} />
        <Selector etiqueta="Estado" valor={filtros.estado} cambiar={cambiar('estado')}
                  opciones={[['', 'Válidos y anulados'], ['valido', 'Válidos'], ['anulado', 'Anulados']]} />
      </Filtros>
      {(error || errorLista) && <p className="error" role="alert">{error || errorLista}</p>}
      <Tabla etiqueta="Pagos" columnas={columnas} filas={datos?.items} cargando={cargando} claseFila={(p) => (p.anulado ? 'atenuada' : '')}
             vacio={{ icono: Receipt, titulo: 'Sin pagos', texto: 'No hay pagos con esos filtros.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

// --- Comprobantes con error -----------------------------------------------------------------

function ComprobantesConError({ editar }) {
  const [error, setError] = useState(null)
  const [aviso, setAviso] = useState(null)
  const { datos, error: errorLista, cargando, recargar, paginacion } = usePaginado('/api/caja/comprobantes/errores', {})

  async function reintentar(c) {
    setError(null)
    setAviso(null)
    try {
      await api(`/api/caja/comprobantes/tareas/${c.tarea_id}/reintentar`, { metodo: 'POST' })
      setAviso(`${TIPO_COMPROBANTE[c.tipo]} ${c.numero}: vuelve a la cola.`)
      recargar()
    } catch (err) { setError(err.message) }
  }

  const columnas = [
    { id: 'numero', titulo: 'Comprobante', celda: (c) => (
      <><b className="nowrap">{TIPO_COMPROBANTE[c.tipo]} {c.numero}</b><span className="segunda-linea">Recibo {c.recibo} · {fechaCorta(c.fecha)}</span></>) },
    { id: 'cliente', titulo: 'Cliente', ancho: '24%', celda: (c) => (
      <>{c.cliente}<span className="segunda-linea">{c.cliente_documento} · Alumno: {c.alumno}</span></>) },
    { id: 'total', titulo: 'Total', numero: true, celda: (c) => <b>{soles(c.total)}</b> },
    { id: 'error', titulo: 'Qué pasó', ancho: '30%', celda: (c) => (
      <>
        <EstadoComprobante c={c} />
        <span className="segunda-linea">
          {c.accion === 'anular' ? 'No se pudo anular' : c.accion === 'emitir' ? 'No se pudo enviar' : 'SUNAT lo rechazó'}
          {c.accion && ` (${plural(c.intentos, 'intento', 'intentos')})`}{c.error && `: ${c.error}`}
        </span>
      </>) },
    editar && { id: 'acciones', titulo: 'Acciones', acciones: true, celda: (c) => (c.tarea_id ? (
      <button type="button" className="boton secundario" onClick={() => reintentar(c)}>
        <RotateCw size={16} aria-hidden="true" /> Reintentar</button>
    ) : null) },
  ].filter(Boolean)
  return (
    <>
      <Encabezado titulo="Comprobantes con error"
                  descripcion="Boletas y facturas que SUNAT rechazó, y las que no se pudieron enviar o anular tras 5 intentos automáticos. El recibo interno de esos pagos sigue valiendo." />
      {aviso && <p className="tenue" role="status">{aviso}</p>}
      {(error || errorLista) && <p className="error" role="alert">{error || errorLista}</p>}
      <Tabla etiqueta="Comprobantes con error" columnas={columnas} filas={datos?.items} cargando={cargando}
             clave={(c) => `${c.id}-${c.tarea_id ?? 'r'}`}
             vacio={{ icono: FileWarning, titulo: 'Sin comprobantes con error', texto: 'Todo lo enviado está al día.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

// --- Cierres de caja ------------------------------------------------------------------------

function Cajas() {
  const [filtros, setFiltros] = useState({ desde: primeroDeMes(), hasta: hoyLima() })
  const { datos, error, cargando, paginacion } = usePaginado('/api/caja/cajas', filtros)
  const columnas = [
    { id: 'cajero', titulo: 'Cajero', ancho: '24%', celda: (c) => <Persona nombre={c.cajero} detalle={fechaCorta(c.fecha)} /> },
    { id: 'horario', titulo: 'Abierta / cerrada', ocultarEnCelular: true, celda: (c) => (
      <>{fechaHora(c.abierta_en)}<span className="segunda-linea">{c.cerrada_en ? fechaHora(c.cerrada_en) : 'Sigue abierta'}</span></>) },
    { id: 'pagos', titulo: 'Pagos', numero: true, celda: (c) => c.pagos },
    { id: 'total', titulo: 'Total', numero: true, celda: (c) => <b>{soles(c.total)}</b> },
    { id: 'efectivo', titulo: 'Efectivo', numero: true, celda: (c) => soles(c.totales.efectivo) },
    { id: 'contado', titulo: 'Contado', numero: true, vacio: (c) => c.contado === null, celda: (c) => (c.contado === null ? '—' : soles(c.contado)) },
    { id: 'diferencia', titulo: 'Diferencia', celda: (c) => (c.abierta ? <Insignia tono="info">Abierta</Insignia>
      : Number(c.diferencia) === 0 ? <Insignia tono="bien">Cuadra</Insignia>
        : <Insignia tono="falta">{Number(c.diferencia) > 0 ? 'Sobra' : 'Falta'} {soles(Math.abs(Number(c.diferencia)).toFixed(2))}</Insignia>) },
  ]
  return (
    <>
      <Encabezado titulo="Cierres de caja" descripcion="Cada cajero abre y cierra su caja del día. La diferencia compara el efectivo contado con el cobrado en efectivo." />
      <Filtros total={datos && plural(datos.total, 'caja', 'cajas')}>
        <label className="selector"><span className="solo-lectores">Desde</span>
          <input type="date" aria-label="Desde" value={filtros.desde} onChange={(e) => setFiltros({ ...filtros, desde: e.target.value })} /></label>
        <label className="selector"><span className="solo-lectores">Hasta</span>
          <input type="date" aria-label="Hasta" value={filtros.hasta} onChange={(e) => setFiltros({ ...filtros, hasta: e.target.value })} /></label>
      </Filtros>
      {error && <p className="error">{error}</p>}
      <Tabla etiqueta="Cierres de caja" columnas={columnas} filas={datos?.items} cargando={cargando}
             vacio={{ icono: Wallet, titulo: 'Sin cajas', texto: 'Nadie abrió caja en esas fechas.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

// --- Gastos ---------------------------------------------------------------------------------

function Gastos({ editar }) {
  const [filtros, setFiltros] = useState({ q: '', categoria_id: '', estado: '', desde: primeroDeMes(), hasta: hoyLima() })
  const [categorias, setCategorias] = useState([])
  const [nuevo, setNuevo] = useState(false)
  const [verCategorias, setVerCategorias] = useState(false)
  const [error, setError] = useState(null)
  const { datos, error: errorLista, cargando, recargar, paginacion } = usePaginado('/api/caja/gastos', { ...filtros, q: filtros.q.trim() })
  const cargarCategorias = useCallback(() => api('/api/caja/categorias').then(setCategorias).catch(() => {}), [])
  useEffect(() => { cargarCategorias() }, [cargarCategorias])
  const cambiar = (k) => (v) => setFiltros({ ...filtros, [k]: v })

  async function anular(g) {
    const motivo = prompt(`¿Por qué se anula el gasto «${g.descripcion}»?`)
    if (!motivo) return
    setError(null)
    try { await api(`/api/caja/gastos/${g.id}/anular`, { metodo: 'POST', datos: { motivo } }); recargar() }
    catch (err) { setError(err.message) }
  }

  const columnas = [
    { id: 'gasto', titulo: 'Gasto', ancho: '30%', celda: (g) => (
      <><b>{g.descripcion}</b><span className="segunda-linea">{g.categoria} · {fechaCorta(g.fecha)}</span></>) },
    { id: 'comprobante', titulo: 'Comprobante', ocultarEnCelular: true, vacio: (g) => !g.comprobante_tipo && !g.comprobante_numero,
      celda: (g) => [g.comprobante_tipo, g.comprobante_numero].filter(Boolean).join(' ') || '—' },
    { id: 'medio', titulo: 'Medio', celda: (g) => MEDIO[g.medio] },
    { id: 'monto', titulo: 'Monto', numero: true, celda: (g) => <b>{soles(g.monto)}</b> },
    { id: 'estado', titulo: 'Estado', celda: (g) => (g.anulado
      ? <><Insignia tono="falta">Anulado</Insignia><span className="segunda-linea">{g.anulado_motivo}</span></>
      : <Insignia tono="bien">Válido</Insignia>) },
    { id: 'acciones', titulo: 'Acciones', acciones: true, celda: (g) => (
      <MenuAcciones etiqueta={g.descripcion}
                    principal={g.archivo ? { texto: 'Archivo', icono: Paperclip, alHacer: () => descargar(`/api/caja/gastos/${g.id}/archivo`, `gasto-${g.id}`).catch((e) => setError(e.message)) } : undefined}
                    opciones={editar && !g.anulado ? [{ texto: 'Anular gasto', peligro: true, alHacer: () => anular(g) }] : []} />) },
  ]
  return (
    <>
      <Encabezado titulo="Gastos" descripcion="Salidas de dinero del colegio con su comprobante. Nada se borra: se anula con motivo. El mismo día lo anula quien lo registró; después, el director o un rol con permiso para anular."
                  acciones={editar && (
                    <>
                      <button className="boton secundario" onClick={() => setVerCategorias(!verCategorias)}>Categorías</button>
                      <button className="boton" onClick={() => setNuevo(true)}><Plus size={18} aria-hidden="true" /> Gasto</button>
                    </>)} />
      {verCategorias && <Categorias categorias={categorias} recargar={cargarCategorias} cerrar={() => setVerCategorias(false)} />}
      {nuevo && <FormGasto categorias={categorias.filter((c) => c.activa)} cerrar={() => setNuevo(false)}
                           alGuardar={() => { setNuevo(false); recargar(); cargarCategorias() }} />}
      {datos && <Cifras items={[{ etiqueta: 'Gastado (válidos)', valor: soles(datos.suma), tono: 'falta' }]} />}
      <Filtros total={datos && plural(datos.total, 'gasto', 'gastos')}>
        <Buscador valor={filtros.q} cambiar={cambiar('q')} placeholder="Descripción o n.° de comprobante" />
        <label className="selector"><span className="solo-lectores">Desde</span>
          <input type="date" aria-label="Desde" value={filtros.desde} onChange={(e) => cambiar('desde')(e.target.value)} /></label>
        <label className="selector"><span className="solo-lectores">Hasta</span>
          <input type="date" aria-label="Hasta" value={filtros.hasta} onChange={(e) => cambiar('hasta')(e.target.value)} /></label>
        <Selector etiqueta="Categoría" valor={filtros.categoria_id} cambiar={cambiar('categoria_id')}
                  opciones={[['', 'Todas las categorías'], ...categorias.map((c) => [String(c.id), c.nombre])]} />
        <Selector etiqueta="Estado" valor={filtros.estado} cambiar={cambiar('estado')}
                  opciones={[['', 'Válidos y anulados'], ['valido', 'Válidos'], ['anulado', 'Anulados']]} />
      </Filtros>
      {(error || errorLista) && <p className="error" role="alert">{error || errorLista}</p>}
      <Tabla etiqueta="Gastos" columnas={columnas} filas={datos?.items} cargando={cargando} claseFila={(g) => (g.anulado ? 'atenuada' : '')}
             vacio={{ icono: Wallet, titulo: 'Sin gastos', texto: 'No hay gastos con esos filtros.' }} />
      {paginacion && <Paginacion {...paginacion} />}
    </>
  )
}

function FormGasto({ categorias, cerrar, alGuardar }) {
  const [form, setForm] = useState({ fecha: hoyLima(), categoria_id: categorias[0]?.id || '', descripcion: '', monto: '',
    medio: 'efectivo', comprobante_tipo: '', comprobante_numero: '' })
  const [archivo, setArchivo] = useState(null)
  const [error, setError] = useState(null)
  const campo = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    if (archivo && archivo.size > 5 * 1024 * 1024) { setError('El archivo pesa más de 5 MB'); return }
    const datos = { ...form, categoria_id: Number(form.categoria_id), comprobante_tipo: form.comprobante_tipo.trim() || null,
      comprobante_numero: form.comprobante_numero.trim() || null }
    const f = new FormData()
    f.append('datos', JSON.stringify(datos))
    if (archivo) f.append('archivo', archivo)
    try { await api('/api/caja/gastos', { metodo: 'POST', formulario: f }); alGuardar() } catch (err) { setError(err.message) }
  }

  return (
    <form className="tarjeta-panel form-pensiones" onSubmit={guardar}>
      <h3>Nuevo gasto</h3>
      <div className="fila-form sin-margen">
        <label>Fecha<input type="date" required max={hoyLima()} value={form.fecha} onChange={campo('fecha')} /></label>
        <label>Categoría
          <select required value={form.categoria_id} onChange={campo('categoria_id')}>
            {categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
        </label>
        <label>Monto (S/)<input inputMode="decimal" required pattern="\d+(\.\d{1,2})?" value={form.monto} onChange={campo('monto')} /></label>
        <label>Medio
          <select value={form.medio} onChange={campo('medio')}>{MEDIOS.map(([m, t]) => <option key={m} value={m}>{t}</option>)}</select>
        </label>
      </div>
      <label>Descripción<input required minLength={2} maxLength={200} value={form.descripcion} onChange={campo('descripcion')}
                              placeholder="Recibo de luz de octubre" /></label>
      <div className="fila-form sin-margen">
        <label>Comprobante<input maxLength={30} value={form.comprobante_tipo} onChange={campo('comprobante_tipo')} placeholder="Boleta, factura…" /></label>
        <label>N.° de comprobante<input maxLength={30} value={form.comprobante_numero} onChange={campo('comprobante_numero')} /></label>
        <label>Foto o PDF (hasta 5 MB)
          <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" onChange={(e) => setArchivo(e.target.files[0] || null)} />
        </label>
      </div>
      <div className="acciones">
        <button className="boton">Guardar gasto</button>
        <button type="button" className="enlace" onClick={cerrar}>Cancelar</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  )
}

function Categorias({ categorias, recargar, cerrar }) {
  const [nombre, setNombre] = useState('')
  const [error, setError] = useState(null)

  async function llamar(fn) {
    setError(null)
    try { await fn(); await recargar(); return true } catch (err) { setError(err.message); return false }
  }

  async function crear(e) {
    e.preventDefault()
    if (await llamar(() => api('/api/caja/categorias', { metodo: 'POST', datos: { nombre } }))) setNombre('')
  }

  return (
    <div className="tarjeta-panel form-pensiones">
      <h3>Categorías de gasto</h3>
      <ul className="lista-montos">
        {categorias.map((c) => (
          <li key={c.id} className={c.activa ? undefined : 'atenuada'}>
            <span>{c.nombre}</span>
            <span className="tenue">{plural(c.usos, 'gasto', 'gastos')}</span>
            <button className="enlace" onClick={() => llamar(() => api(`/api/caja/categorias/${c.id}`, {
              metodo: 'PUT', datos: { nombre: c.nombre, activa: !c.activa } }))}>{c.activa ? 'Desactivar' : 'Activar'}</button>
          </li>
        ))}
      </ul>
      <form className="fila-form sin-margen" onSubmit={crear}>
        <label>Nueva categoría<input required maxLength={60} value={nombre} onChange={(e) => setNombre(e.target.value)} /></label>
        <div className="acciones"><button className="boton secundario">Agregar</button>
          <button type="button" className="enlace" onClick={cerrar}>Cerrar</button></div>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  )
}

// --- Reportes -------------------------------------------------------------------------------

const AGRUPAR = [['dia', 'Por día'], ['concepto', 'Por concepto'], ['medio', 'Por medio de pago'], ['cajero', 'Por cajero']]

function Reportes() {
  const [rango, setRango] = useState({ desde: primeroDeMes(), hasta: hoyLima() })
  const [agrupar, setAgrupar] = useState('dia')
  const [ingresos, setIngresos] = useState(null)
  const [gastos, setGastos] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!rango.desde || !rango.hasta) return undefined
    const p = `desde=${rango.desde}&hasta=${rango.hasta}`
    let vivo = true
    setError(null)
    Promise.all([api(`/api/caja/reportes/ingresos?${p}&agrupar=${agrupar}`), api(`/api/caja/reportes/gastos?${p}`)])
      .then(([i, g]) => { if (vivo) { setIngresos(i); setGastos(g) } })
      .catch((e) => vivo && setError(e.message))
    return () => { vivo = false }
  }, [rango, agrupar])

  const excel = (que) => descargar(`/api/caja/reportes/${que}.xlsx?desde=${rango.desde}&hasta=${rango.hasta}${que === 'ingresos' ? `&agrupar=${agrupar}` : ''}`,
    `${que}-${rango.desde}-${rango.hasta}.xlsx`).catch((e) => setError(e.message))
  const columnas = (cuenta) => [
    { id: 'grupo', titulo: AGRUPAR.find(([k]) => k === agrupar)?.[1].replace('Por ', '') || 'Grupo', celda: (f) => <b>{f.grupo}</b> },
    { id: 'n', titulo: cuenta === 'pagos' ? 'Pagos' : 'Gastos', numero: true, celda: (f) => f[cuenta] },
    { id: 'total', titulo: 'Total', numero: true, celda: (f) => soles(f.total) },
  ]
  const neto = ingresos && gastos ? aSoles(centimos(ingresos.total) - centimos(gastos.total)) : null
  return (
    <>
      <Encabezado titulo="Reportes" descripcion="Solo pagos y gastos válidos (los anulados no cuentan)." />
      <Filtros>
        <label className="selector"><span className="solo-lectores">Desde</span>
          <input type="date" aria-label="Desde" value={rango.desde} onChange={(e) => setRango({ ...rango, desde: e.target.value })} /></label>
        <label className="selector"><span className="solo-lectores">Hasta</span>
          <input type="date" aria-label="Hasta" value={rango.hasta} onChange={(e) => setRango({ ...rango, hasta: e.target.value })} /></label>
      </Filtros>
      {error && <p className="error" role="alert">{error}</p>}
      {ingresos && gastos && (
        <Cifras items={[{ etiqueta: 'Ingresos', valor: soles(ingresos.total), tono: 'bien' },
          { etiqueta: 'Gastos', valor: soles(gastos.total), tono: 'falta' },
          { etiqueta: 'Ingresos menos gastos', valor: soles(neto) }]} />
      )}
      <div className="reporte-cabeza">
        <h3>Ingresos</h3>
        <div className="acciones">
          <Selector etiqueta="Agrupar ingresos" valor={agrupar} cambiar={setAgrupar} opciones={AGRUPAR} />
          <button className="boton secundario" onClick={() => excel('ingresos')}><FileSpreadsheet size={18} aria-hidden="true" /> Excel</button>
        </div>
      </div>
      <Tabla etiqueta="Ingresos" columnas={columnas('pagos')} filas={ingresos?.items} cargando={!ingresos} clave={(f) => f.grupo}
             vacio={{ icono: Receipt, titulo: 'Sin ingresos', texto: 'No hubo pagos en esas fechas.' }} />
      <div className="reporte-cabeza">
        <h3>Gastos por categoría</h3>
        <button className="boton secundario" onClick={() => excel('gastos')}><FileSpreadsheet size={18} aria-hidden="true" /> Excel</button>
      </div>
      <Tabla etiqueta="Gastos por categoría" columnas={[{ ...columnas('gastos')[0], titulo: 'Categoría' }, ...columnas('gastos').slice(1)]}
             filas={gastos?.items} cargando={!gastos} clave={(f) => f.grupo}
             vacio={{ icono: Wallet, titulo: 'Sin gastos', texto: 'No hubo gastos en esas fechas.' }} />
    </>
  )
}
