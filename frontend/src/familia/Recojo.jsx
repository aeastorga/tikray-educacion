// Recojo seguro, app de la familia: quién puede recoger a cada hijo (entra activo de inmediato), autorizar a
// alguien solo por un día. Los apoderados siempre pueden recogerlo.
import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft } from 'lucide-react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api.js'
import { CamposPersona, FotoProtegida, PERSONA_VACIA, SubirFoto } from '../espacios/RecojoAlumno.jsx'
import { useConfirmar } from '../espacios/comun/index.js'

const fechaTexto = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-PE', { weekday: 'long', day: 'numeric', month: 'long' })

function sumarDias(iso, dias) {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + dias)
  return d.toISOString().slice(0, 10)
}

export default function RecojoFamilia() {
  const { yo } = useOutletContext()
  const navegar = useNavigate()
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const apagado = yo?.modulos?.recojo === false
  const activa = yo?.estado === 'activo'
  const cargar = useCallback(() => api('/api/familia/recojo').then(setD).catch((e) => setError(e.message)), [])
  useEffect(() => { if (yo && !apagado && activa) cargar() }, [yo, apagado, activa, cargar])

  if (apagado) return <p className="tenue">El colegio no usa recojo seguro en la app.</p>
  if (yo && !activa) return <p className="tenue">Podrá elegir quién recoge a sus hijos cuando el colegio apruebe su cuenta.</p>
  return (
    <>
      <button type="button" className="enlace" onClick={() => navegar('/familia')}><ChevronLeft size={18} aria-hidden="true" /> Inicio</button>
      <div className="saludo"><h1>Recojo seguro</h1>
        <p className="tenue">Quién puede recoger a sus hijos. Usted y los demás apoderados siempre pueden; la portería
          verifica a las demás personas con su documento.</p>
      </div>
      {error && <p className="error">{error}</p>}
      {!d && !error && <p className="tenue">Cargando…</p>}
      {d?.hijos.length === 0 && <p className="tenue">No hay alumnos vinculados a su cuenta en este colegio.</p>}
      {d?.hijos.map((h) => <RecojoHijo key={h.id} h={h} d={d} varios={d.hijos.length > 1} recargar={cargar} />)}
    </>
  )
}

function RecojoHijo({ h, d, varios, recargar }) {
  const { confirmar } = useConfirmar()
  const [form, setForm] = useState(null)
  const [dia, setDia] = useState(null)
  const [verInactivos, setVerInactivos] = useState(false)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const nombre = h.nombres.split(' ')[0]
  const activos = h.autorizados.filter((x) => x.activo)
  const inactivos = h.autorizados.filter((x) => !x.activo)

  async function hacer(promesa, alTerminar) {
    setError(null)
    try { await promesa; alTerminar?.(); recargar() } catch (err) { setError(err.message) }
  }

  function datosDe(x, extra = {}) {
    return { nombres: x.nombres, apellidos: x.apellidos, tipo_documento: x.tipo_documento, numero_documento: x.numero_documento,
      parentesco: x.parentesco, celular: x.celular || null, ...extra }
  }

  function guardar(e) {
    e.preventDefault()
    const { id, ...datos } = form
    const cuerpo = datosDe(datos)
    hacer(id ? api(`/api/familia/recojo/autorizados/${id}`, { metodo: 'PUT', datos: cuerpo })
      : api(`/api/familia/recojo/hijos/${h.id}/autorizados`, { metodo: 'POST', datos: cuerpo }), () => setForm(null))
  }

  async function cambiarActivo(x) {
    if (x.activo && !await confirmar({ titulo: 'Quitar de la lista', texto: `${x.nombres} ya no podrá recoger a ${nombre}.`, accion: 'Quitar' })) return
    hacer(api(`/api/familia/recojo/autorizados/${x.id}`, { metodo: 'PUT', datos: datosDe(x, { activo: !x.activo }) }))
  }

  function autorizarDia(e) {
    e.preventDefault()
    const { celular, ...datos } = dia
    hacer(api(`/api/familia/recojo/hijos/${h.id}/del-dia`, { metodo: 'POST', datos }), () => setDia(null))
  }

  async function anular(x) {
    if (!await confirmar({ titulo: 'Anular permiso', texto: `${x.nombres} ya no podrá recogerlo el ${fechaTexto(x.fecha)}.`, accion: 'Anular', peligro: true })) return
    hacer(api(`/api/familia/recojo/del-dia/${x.id}/anular`, { metodo: 'POST' }))
  }

  return (
    <section className="tarjeta-app recojo-hijo">
      {varios && <h2>{h.nombres}</h2>}
      <h3>Pueden recoger a {nombre}</h3>
      {activos.length === 0 && <p className="tenue">Solo sus apoderados. Agregue a quien suele recogerlo (abuelos, tíos, movilidad).</p>}
      <ul className="recojo-personas recojo-filas">
        {activos.map((x) => (
          <li key={x.id}>
            {x.foto ? <FotoProtegida ruta={`/api/familia/recojo/autorizados/${x.id}/foto`} nombre={x.nombres} version={version} />
              : <span className="recojo-foto sin-foto" aria-hidden="true" />}
            <span>
              <b>{x.nombres} {x.apellidos}</b>
              <small className="tenue">{x.parentesco} · {x.tipo_documento} {x.numero_documento}</small>
              <span className="recojo-acciones">
                <button type="button" className="enlace" onClick={() => setForm({ ...PERSONA_VACIA, ...x, celular: x.celular || '' })}>Editar</button>
                <SubirFoto ruta={`/api/familia/recojo/autorizados/${x.id}/foto`} setError={setError}
                           alSubir={() => { setVersion((v) => v + 1); recargar() }} />
                <button type="button" className="enlace" onClick={() => cambiarActivo(x)}>Quitar</button>
              </span>
            </span>
          </li>
        ))}
      </ul>
      {!form && (activos.length < d.max_autorizados
        ? <button type="button" className="boton secundario" onClick={() => setForm({ ...PERSONA_VACIA })}>Agregar persona</button>
        : <p className="tenue">Ya tiene {d.max_autorizados} personas. Quite a una para agregar otra.</p>)}
      {form && (
        <form className="recojo-otro" onSubmit={guardar}>
          <CamposPersona datos={form} set={setForm} />
          <p className="tenue">Sus datos se usan solo para que la portería verifique quién recoge a {nombre}.</p>
          <div className="acciones">
            <button className="boton">{form.id ? 'Guardar' : 'Agregar'}</button>
            <button type="button" className="enlace" onClick={() => setForm(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {inactivos.length > 0 && (
        <details className="recojo-inactivos" open={verInactivos} onToggle={(e) => setVerInactivos(e.currentTarget.open)}>
          <summary>Quitados de la lista ({inactivos.length})</summary>
          <ul className="recojo-filas">
            {inactivos.map((x) => (
              <li key={x.id}>
                <span><b>{x.nombres} {x.apellidos}</b><small className="tenue">{x.parentesco}</small></span>
                <button type="button" className="enlace" onClick={() => cambiarActivo(x)}>Volver a agregar</button>
              </li>
            ))}
          </ul>
        </details>
      )}

      <h3>Solo por un día</h3>
      <p className="tenue">Para alguien que lo recoge una vez. Vale solo ese día.</p>
      {h.del_dia.length > 0 && (
        <ul className="recojo-filas">
          {h.del_dia.map((x) => (
            <li key={x.id}>
              <span><b>{x.nombres} {x.apellidos}</b>
                <small className="tenue">{x.parentesco} · {x.fecha === d.hoy ? 'hoy' : fechaTexto(x.fecha)}</small></span>
              <button type="button" className="enlace" onClick={() => anular(x)}>Anular</button>
            </li>
          ))}
        </ul>
      )}
      {!dia && <button type="button" className="boton secundario" onClick={() => setDia({ ...PERSONA_VACIA, fecha: d.hoy })}>Autorizar por un día</button>}
      {dia && (
        <form className="recojo-otro" onSubmit={autorizarDia}>
          <label className="recojo-fecha">Día
            <input type="date" required value={dia.fecha} min={d.hoy} max={sumarDias(d.hoy, d.dias_adelante)}
                   onChange={(e) => setDia({ ...dia, fecha: e.target.value })} />
          </label>
          <CamposPersona datos={dia} set={setDia} conCelular={false} />
          <div className="acciones">
            <button className="boton">Autorizar</button>
            <button type="button" className="enlace" onClick={() => setDia(null)}>Cancelar</button>
          </div>
        </form>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  )
}
