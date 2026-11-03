// Cliente del backend. Cada colegio es su propio origen (subdominio), así que
// el token guardado aquí solo existe para ese colegio.

// La sesión de la familia va aparte: en un mismo celular puede haber un docente que también es padre.
const CLAVE_TOKEN = 'tikray.token'
export const CLAVE_TOKEN_FAMILIA = 'tikray.token.familia'

export const esPlataforma = window.location.hostname.startsWith('plataforma.')

export function leerToken(clave = CLAVE_TOKEN) {
  try { return localStorage.getItem(clave) } catch { return null }
}

export function guardarToken(token, clave = CLAVE_TOKEN) {
  try {
    if (token) localStorage.setItem(clave, token)
    else localStorage.removeItem(clave)
  } catch { /* modo privado: la sesión dura lo que la pestaña */ }
}

const deFamilia = (ruta) => ruta.startsWith('/api/familia/')

export class ErrorApi extends Error {
  constructor(estado, detalle) {
    const texto = typeof detalle === 'string' ? detalle : detalle?.mensaje || 'Error inesperado'
    super(texto)
    this.estado = estado
    this.motivos = detalle?.motivos || []
  }
}

// `sinSalir`: ante un 401 la pantalla se queda (la portería sigue marcando sin sesión y avisa).
// `formulario`: un FormData ya armado (datos + varios archivos).
export async function api(ruta, { metodo = 'GET', datos, archivo, formulario, sinSalir = false } = {}) {
  const cabeceras = {}
  const clave = deFamilia(ruta) ? CLAVE_TOKEN_FAMILIA : CLAVE_TOKEN
  const token = leerToken(clave)
  if (token) cabeceras.Authorization = `Bearer ${token}`
  let cuerpo
  if (formulario) {
    cuerpo = formulario
  } else if (archivo) {
    cuerpo = new FormData()
    cuerpo.append('archivo', archivo)
  } else if (datos !== undefined) {
    cabeceras['Content-Type'] = 'application/json'
    cuerpo = JSON.stringify(datos)
  }
  const r = await fetch(ruta, { method: metodo, headers: cabeceras, body: cuerpo })
  if (r.status === 401 && token) {
    guardarToken(null, clave)
    if (!sinSalir) window.dispatchEvent(new Event(deFamilia(ruta) ? 'sesion-familia-cerrada' : 'sesion-cerrada'))
  }
  if (r.status === 204) return null
  const json = await r.json().catch(() => null)
  if (!r.ok) {
    const detalle = Array.isArray(json?.detail) ? 'Revisa los datos ingresados' : json?.detail
    throw new ErrorApi(r.status, detalle)
  }
  return json
}

// Descarga un archivo protegido (PDF, Excel) con el token y lo abre o guarda.
export async function descargar(ruta, nombre) {
  const token = leerToken(deFamilia(ruta) ? CLAVE_TOKEN_FAMILIA : CLAVE_TOKEN)
  const r = await fetch(ruta, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    throw new ErrorApi(r.status, json?.detail)
  }
  guardarArchivo(await r.blob(), nombre)
}

export function guardarArchivo(blob, nombre) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}
