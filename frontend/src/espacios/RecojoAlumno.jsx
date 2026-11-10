// Recojo seguro en la ficha del alumno: quién puede recogerlo. Los apoderados siempre pueden; la lista de
// autorizados (máximo 5 activos) la llenan la secretaría y el apoderado desde la app. Nada se borra: se desactiva.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera } from 'lucide-react'
import { api, leerToken } from '../api.js'
import { Insignia } from './comun/index.js'
import './recojo.css'

const TIPOS_DOC = ['DNI', 'CE', 'PAS', 'OTRO']
export const PERSONA_VACIA = { nombres: '', apellidos: '', tipo_documento: 'DNI', numero_documento: '', parentesco: '', celular: '' }

export function CamposPersona({ datos, set, conCelular = true }) {
  const campo = (k, etiqueta, extra = {}) => (
    <label>{etiqueta}<input value={datos[k] || ''} onChange={(e) => set({ ...datos, [k]: e.target.value })} {...extra} /></label>
  )
  return (
    <div className="recojo-campos">
      {campo('nombres', 'Nombres', { required: true, maxLength: 120 })}
      {campo('apellidos', 'Apellidos', { required: true, maxLength: 120 })}
      <label>Documento
        <select value={datos.tipo_documento} onChange={(e) => set({ ...datos, tipo_documento: e.target.value })}>
          {TIPOS_DOC.map((t) => <option key={t}>{t}</option>)}
        </select>
      </label>
      {campo('numero_documento', 'Número', { required: true, maxLength: 15, inputMode: datos.tipo_documento === 'DNI' ? 'numeric' : 'text' })}
      {campo('parentesco', 'Parentesco', { required: true, maxLength: 30, placeholder: 'Tía, abuelo, movilidad…' })}
      {conCelular && campo('celular', 'Celular (opcional)', { inputMode: 'tel', maxLength: 15 })}
    </div>
  )
}

// Foto protegida: se pide con la sesión de quien mira (personal o familia).
export function FotoProtegida({ ruta, nombre, version }) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    let vivo = true
    let creada = null
    const familia = ruta.startsWith('/api/familia/')
    const token = leerToken(familia ? 'tikray.token.familia' : undefined)
    fetch(ruta, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b && vivo) { creada = URL.createObjectURL(b); setUrl(creada) } })
      .catch(() => {})
    return () => { vivo = false; if (creada) URL.revokeObjectURL(creada) }
  }, [ruta, version])
  return url ? <img className="recojo-foto" src={url} alt={`Foto de ${nombre}`} /> : <span className="recojo-foto sin-foto" aria-hidden="true" />
}

export function SubirFoto({ ruta, alSubir, setError }) {
  const entrada = useRef(null)
  async function subir(e) {
    const archivo = e.target.files?.[0]
    e.target.value = ''
    if (!archivo) return
    setError(null)
    try { await api(ruta, { metodo: 'PUT', archivo }); alSubir() } catch (err) { setError(err.message) }
  }
  return (
    <>
      <input ref={entrada} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={subir} />
      <button type="button" className="enlace" onClick={() => entrada.current?.click()}>
        <Camera size={16} aria-hidden="true" /> Foto
      </button>
    </>
  )
}

export default function RecojoAlumno({ alumnoId, editar }) {
  const [d, setD] = useState(null)
  const [form, setForm] = useState(null) // { id?, ...persona }
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const cargar = useCallback(() => api(`/api/recojo/alumnos/${alumnoId}`).then(setD).catch((e) => setError(e.message)), [alumnoId])
  useEffect(() => { cargar() }, [cargar])

  if (!d) return error ? <p className="error">{error}</p> : null
  const activos = d.autorizados.filter((x) => x.activo).length

  async function guardar(e) {
    e.preventDefault()
    setError(null)
    const { id, ...datos } = form
    const cuerpo = { ...datos, celular: datos.celular || null }
    try {
      if (id) await api(`/api/recojo/autorizados/${id}`, { metodo: 'PUT', datos: cuerpo })
      else await api(`/api/recojo/alumnos/${alumnoId}/autorizados`, { metodo: 'POST', datos: cuerpo })
      setForm(null)
      cargar()
    } catch (err) { setError(err.message) }
  }

  async function cambiarActivo(x) {
    if (x.activo && !confirm(`¿Desactivar a ${x.nombres} ${x.apellidos}? Ya no podrá recogerlo.`)) return
    setError(null)
    try {
      await api(`/api/recojo/autorizados/${x.id}`, { metodo: 'PUT', datos: {
        nombres: x.nombres, apellidos: x.apellidos, tipo_documento: x.tipo_documento, numero_documento: x.numero_documento,
        parentesco: x.parentesco, celular: x.celular, activo: !x.activo } })
      cargar()
    } catch (err) { setError(err.message) }
  }

  return (
    <section className="recojo-ficha" aria-labelledby="t-recojo-ficha">
      <h3 id="t-recojo-ficha">Recojo seguro</h3>
      <p className="tenue">
        Pueden recogerlo sus apoderados y estas personas. La portería las ve al marcar la salida.
      </p>
      <ul className="lista recojo-personas">
        {d.apoderados.map((p) => (
          <li key={`a${p.id}`}>
            <span className="recojo-foto sin-foto" aria-hidden="true" />
            <span><b>{p.apellidos}, {p.nombres}</b> · {p.parentesco} · {p.tipo_documento} {p.numero_documento}
              {' '}<Insignia tono="info">Apoderado</Insignia></span>
          </li>
        ))}
        {d.autorizados.map((x) => (
          <li key={x.id} className={x.activo ? undefined : 'inactivo'}>
            {x.foto ? <FotoProtegida ruta={`/api/recojo/autorizados/${x.id}/foto`} nombre={x.nombres} version={version} />
              : <span className="recojo-foto sin-foto" aria-hidden="true" />}
            <span>
              <b>{x.apellidos}, {x.nombres}</b> · {x.parentesco} · {x.tipo_documento} {x.numero_documento}
              {x.celular && <> · {x.celular}</>}
              {' '}{x.activo ? <Insignia tono="bien">Autorizado</Insignia> : <Insignia tono="neutro">Desactivado</Insignia>}
              {x.origen === 'familia' && <span className="tenue"> · lo agregó el apoderado</span>}
              {editar && (
                <span className="recojo-acciones">
                  {x.activo && <button type="button" className="enlace" onClick={() => setForm({ ...PERSONA_VACIA, ...x, celular: x.celular || '' })}>Editar</button>}
                  {x.activo && <SubirFoto ruta={`/api/recojo/autorizados/${x.id}/foto`} setError={setError}
                                          alSubir={() => { setVersion((v) => v + 1); cargar() }} />}
                  <button type="button" className="enlace" onClick={() => cambiarActivo(x)}>{x.activo ? 'Desactivar' : 'Activar'}</button>
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {d.del_dia.length > 0 && (
        <>
          <h4>Autorizados por un día (los dio el apoderado)</h4>
          <ul className="lista">
            {d.del_dia.map((x) => (
              <li key={x.id}><b>{x.apellidos}, {x.nombres}</b> · {x.parentesco} · {x.tipo_documento} {x.numero_documento} ·{' '}
                {new Date(`${x.fecha}T12:00:00`).toLocaleDateString('es-PE', { weekday: 'short', day: 'numeric', month: 'short' })}</li>
            ))}
          </ul>
        </>
      )}
      {editar && !form && (
        activos < d.max_autorizados
          ? <button type="button" className="boton secundario" onClick={() => setForm({ ...PERSONA_VACIA })}>Agregar autorizado</button>
          : <p className="tenue">Ya tiene {d.max_autorizados} autorizados activos. Desactiva uno para agregar otro.</p>
      )}
      {form && (
        <form className="tarjeta ancho recojo-otro" onSubmit={guardar}>
          <h4>{form.id ? 'Editar autorizado' : 'Nuevo autorizado'}</h4>
          <CamposPersona datos={form} set={setForm} />
          <p className="tenue">Su documento y su foto se usan solo para verificar quién recoge al alumno.</p>
          <div className="acciones">
            <button className="boton">Guardar</button>
            <button type="button" className="enlace" onClick={() => setForm(null)}>Cancelar</button>
          </div>
        </form>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  )
}
