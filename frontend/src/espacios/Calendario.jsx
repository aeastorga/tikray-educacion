// Calendario escolar del panel (permiso "calendario"): vista de mes y lista de próximos, con los días sin clases
// de Estructura. Con "editar": crear, editar y anular eventos (nada se borra) y elegir si se avisa a las familias.
// El PDF del mes es para imprimir o mandar por WhatsApp.
import { FileDown, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, descargar } from '../api.js'
import { DetalleDia, ListaProximos, MesCalendario, NavegarMes } from './CalendarioMes.jsx'
import { Cargando, Encabezado, Mensaje } from './comun/index.js'
import './calendario.css'

const VACIO = { titulo: '', tipo: 'actuacion', inicio: '', fin: '', hora: '', descripcion: '', alcance: 'colegio',
  niveles: [], secciones: [], avisar: false }

export default function Calendario({ editar }) {
  const [opciones, setOpciones] = useState(null)
  const [form, setForm] = useState(null)  // evento que se crea o edita
  const [version, setVersion] = useState(0)
  const [mensaje, setMensaje] = useState(null)
  useEffect(() => { api('/api/calendario/opciones').then(setOpciones).catch(() => {}) }, [])

  const nuevo = (fecha) => { setMensaje(null); setForm({ ...VACIO, inicio: fecha || opciones?.hoy || '' }) }
  const alGuardar = (r, era) => {
    setForm(null)
    setVersion((v) => v + 1)
    const avisos = r.avisos ? ` Se avisó a ${r.avisos} familia${r.avisos === 1 ? '' : 's'}.` : ''
    setMensaje(`${era ? 'Evento actualizado.' : 'Evento publicado.'}${avisos}`)
  }
  const acciones = editar ? (e) => !e.anulado && (
    <AccionesEvento e={e} editar={() => { setMensaje(null); setForm({ ...VACIO, ...e, fin: e.fin === e.inicio ? '' : e.fin,
      hora: e.hora || '', descripcion: e.descripcion || '' }) }}
                    alAnular={() => { setVersion((v) => v + 1); setMensaje('Evento anulado. Sigue visible como anulado.') }} />
  ) : null

  return (
    <section className="calendario">
      <Encabezado titulo="Calendario escolar"
        descripcion="Eventos del colegio y días sin clases. Los días sin clases se agregan en Padrón › Estructura."
        acciones={editar && !form && (
          <button type="button" className="boton" onClick={() => nuevo()}><Plus size={18} aria-hidden="true" /> Nuevo evento</button>)} />
      <nav className="subpestanas" aria-label="Calendario">
        <NavLink to="/panel/calendario" end>Mes</NavLink>
        <NavLink to="/panel/calendario/proximos">Próximos</NavLink>
      </nav>
      <Mensaje tipo="ok">{mensaje}</Mensaje>
      {form && opciones && <FormEvento form={form} setForm={setForm} opciones={opciones} alGuardar={alGuardar} />}
      <Routes>
        <Route index element={<VistaMes version={version} opciones={opciones} acciones={acciones}
          nuevo={editar && !form ? nuevo : null} />} />
        <Route path="proximos" element={<VistaProximos version={version} acciones={acciones} />} />
      </Routes>
    </section>
  )
}

function Leyenda({ opciones }) {
  if (!opciones) return null
  return (
    <ul className="calendario-leyenda" aria-label="Leyenda">
      {opciones.tipos.map((t) => <li key={t.id} className={`tipo-${t.id}`}><i aria-hidden="true" />{t.nombre}</li>)}
      <li><i className="sin-clases" aria-hidden="true" />Sin clases</li>
    </ul>
  )
}

function VistaMes({ version, opciones, acciones, nuevo }) {
  const [mes, setMes] = useState(null)
  const [d, setD] = useState(null)
  const [dia, setDia] = useState(null)
  const [error, setError] = useState(null)
  const cargar = useCallback(() => {
    api(`/api/calendario/mes${mes ? `?mes=${mes}` : ''}`).then((r) => { setD(r); if (!mes) setMes(r.mes) })
      .catch((e) => setError(e.message))
  }, [mes])
  useEffect(() => { cargar() }, [cargar, version])

  async function pdf() {
    setError(null)
    try { await descargar(`/api/calendario/mes.pdf?mes=${d.mes}`, `calendario-${d.mes}.pdf`) } catch (e) { setError(e.message) }
  }

  if (error && !d) return <Mensaje tipo="error">{error}</Mensaje>
  if (!d) return <Cargando />
  return (
    <>
      <div className="acciones calendario-barra">
        <NavegarMes mes={d.mes} hoy={d.hoy} cambiar={(m) => { setMes(m); setDia(null) }} />
        <button type="button" className="boton secundario" onClick={pdf}><FileDown size={18} aria-hidden="true" /> PDF del mes</button>
      </div>
      {error && <Mensaje tipo="error">{error}</Mensaje>}
      <MesCalendario mes={d.mes} hoy={d.hoy} eventos={d.eventos} sinClases={d.sin_clases} elegido={dia} elegir={setDia} />
      <Leyenda opciones={opciones} />
      {dia && (
        <>
          <DetalleDia dia={dia} eventos={d.eventos} sinClases={d.sin_clases} accionesDe={acciones} />
          {nuevo && <button type="button" className="enlace" onClick={() => nuevo(dia)}>Agregar un evento este día</button>}
        </>
      )}
      {!dia && d.eventos.length > 0 && <p className="tenue">Toque un día para ver el detalle.</p>}
      {!dia && d.eventos.length === 0 && d.sin_clases.length === 0 && <p className="tenue">No hay eventos este mes.</p>}
    </>
  )
}

function VistaProximos({ version, acciones }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { api('/api/calendario/proximos').then(setD).catch((e) => setError(e.message)) }, [version])
  if (error) return <Mensaje tipo="error">{error}</Mensaje>
  if (!d) return <Cargando />
  return <ListaProximos eventos={d.eventos} sinClases={d.sin_clases} accionesDe={acciones} />
}

function AccionesEvento({ e, editar, alAnular }) {
  const [anulando, setAnulando] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState(null)
  async function anular(ev) {
    ev.preventDefault()
    setError(null)
    try {
      await api(`/api/calendario/eventos/${e.id}/anular`, { metodo: 'POST', datos: { motivo } })
      alAnular()
    } catch (err) { setError(err.message) }
  }
  if (anulando) {
    return (
      <form className="form-anular" onSubmit={anular}>
        <label>Motivo de la anulación
          <input required maxLength={200} value={motivo} onChange={(x) => setMotivo(x.target.value)} autoFocus
                 placeholder="Se pasa a otra fecha, lluvia…" />
        </label>
        <p className="tenue">El evento queda visible como anulado y no se manda recordatorio.</p>
        <div className="acciones">
          <button className="boton">Anular evento</button>
          <button type="button" className="enlace" onClick={() => setAnulando(false)}>Cancelar</button>
        </div>
        {error && <Mensaje tipo="error">{error}</Mensaje>}
      </form>
    )
  }
  return (
    <div className="acciones">
      <button type="button" className="enlace" onClick={editar}>Editar</button>
      <button type="button" className="enlace" onClick={() => setAnulando(true)}>Anular</button>
    </div>
  )
}

function FormEvento({ form, setForm, opciones, alGuardar }) {
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const set = (k, v) => setForm({ ...form, [k]: v })
  const alternar = (k, id) => set(k, form[k].includes(id) ? form[k].filter((x) => x !== id) : [...form[k], id])
  const yaAvisado = form.id && form.avisado

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    const datos = { titulo: form.titulo, tipo: form.tipo, inicio: form.inicio, fin: form.fin || null, hora: form.hora || null,
      descripcion: form.descripcion || null, alcance: form.alcance, niveles: form.niveles, secciones: form.secciones,
      avisar: form.avisar }
    try {
      const r = form.id ? await api(`/api/calendario/eventos/${form.id}`, { metodo: 'PUT', datos })
        : await api('/api/calendario/eventos', { metodo: 'POST', datos })
      alGuardar(r, Boolean(form.id))
    } catch (err) { setError(err.message) } finally { setEnviando(false) }
  }

  const porNivel = opciones.niveles.map((n) => ({ ...n, secciones: opciones.secciones.filter((s) => s.nivel_id === n.id) }))
  return (
    <form className="tarjeta-panel form-evento" onSubmit={guardar}>
      <h3>{form.id ? 'Editar evento' : 'Nuevo evento'}</h3>
      <label>Título
        <input required maxLength={120} value={form.titulo} onChange={(e) => set('titulo', e.target.value)}
               placeholder="Actuación por el Día de la Madre" />
      </label>
      <div className="fila-form">
        <label>Tipo
          <select value={form.tipo} onChange={(e) => set('tipo', e.target.value)}>
            {opciones.tipos.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
        </label>
        <label>Fecha
          <input type="date" required value={form.inicio} onChange={(e) => set('inicio', e.target.value)} />
        </label>
        <label>Hasta (si dura varios días)
          <input type="date" value={form.fin} min={form.inicio || undefined} onChange={(e) => set('fin', e.target.value)} />
        </label>
        <label>Hora (opcional)
          <input type="time" value={form.hora} onChange={(e) => set('hora', e.target.value)} />
        </label>
      </div>
      <label>Descripción (opcional)
        <textarea maxLength={1000} value={form.descripcion} onChange={(e) => set('descripcion', e.target.value)}
                  placeholder="Lugar, qué traer, horario de salida…" />
      </label>
      <fieldset>
        <legend>¿Para quién es?</legend>
        <div className="opciones-para">
          {[['colegio', 'Todo el colegio'], ['niveles', 'Uno o varios niveles'], ['secciones', 'Una o varias secciones']].map(([v, t]) => (
            <label key={v}><input type="radio" name="alcance" value={v} checked={form.alcance === v}
                                  onChange={() => set('alcance', v)} /> {t}</label>
          ))}
        </div>
        {form.alcance === 'niveles' && (
          <div className="destinos">
            {opciones.niveles.map((n) => (
              <label key={n.id}><input type="checkbox" checked={form.niveles.includes(n.id)} onChange={() => alternar('niveles', n.id)} /> {n.nombre}</label>
            ))}
          </div>
        )}
        {form.alcance === 'secciones' && (
          <div className="destinos">
            {opciones.secciones.length === 0 && <p className="tenue">No hay secciones en el año escolar activo.</p>}
            {porNivel.filter((n) => n.secciones.length).map((n) => (
              <div key={n.id} style={{ display: 'contents' }}>
                <h5>{n.nombre}</h5>
                {n.secciones.map((s) => (
                  <label key={s.id}><input type="checkbox" checked={form.secciones.includes(s.id)} onChange={() => alternar('secciones', s.id)} /> {s.nombre}</label>
                ))}
              </div>
            ))}
          </div>
        )}
      </fieldset>
      <label className="casilla-avisar">
        <input type="checkbox" checked={form.avisar} onChange={(e) => set('avisar', e.target.checked)} />
        <span>Avisar a las familias
          <small>{yaAvisado ? 'Ya se avisó al publicar. Si cambia la fecha, el recordatorio se programa para la nueva.'
            : 'Les llega una notificación al publicarlo y un recordatorio el día anterior (respetando el horario sin molestar).'}</small>
        </span>
      </label>
      <div className="acciones">
        <button className="boton" disabled={enviando}>{form.id ? 'Guardar cambios' : 'Publicar evento'}</button>
        <button type="button" className="enlace" onClick={() => setForm(null)}>Cancelar</button>
      </div>
      {error && <Mensaje tipo="error">{error}</Mensaje>}
    </form>
  )
}
