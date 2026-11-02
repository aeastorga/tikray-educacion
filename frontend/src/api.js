// Cliente del backend. Cada colegio es su propio origen (subdominio), así que
// el token guardado aquí solo existe para ese colegio.

const CLAVE_TOKEN = 'tikray.token'

export const esPlataforma = window.location.hostname.startsWith('plataforma.')

export function leerToken() {
  try { return localStorage.getItem(CLAVE_TOKEN) } catch { return null }
}

export function guardarToken(token) {
  try {
    if (token) localStorage.setItem(CLAVE_TOKEN, token)
    else localStorage.removeItem(CLAVE_TOKEN)
  } catch { /* modo privado: la sesión dura lo que la pestaña */ }
}

export class ErrorApi extends Error {
  constructor(estado, detalle) {
    const texto = typeof detalle === 'string' ? detalle : detalle?.mensaje || 'Error inesperado'
    super(texto)
    this.estado = estado
    this.motivos = detalle?.motivos || []
  }
}

export async function api(ruta, { metodo = 'GET', datos, archivo } = {}) {
  const cabeceras = {}
  const token = leerToken()
  if (token) cabeceras.Authorization = `Bearer ${token}`
  let cuerpo
  if (archivo) {
    cuerpo = new FormData()
    cuerpo.append('archivo', archivo)
  } else if (datos !== undefined) {
    cabeceras['Content-Type'] = 'application/json'
    cuerpo = JSON.stringify(datos)
  }
  const r = await fetch(ruta, { method: metodo, headers: cabeceras, body: cuerpo })
  if (r.status === 401 && token) {
    guardarToken(null)
    window.dispatchEvent(new Event('sesion-cerrada'))
  }
  if (r.status === 204) return null
  const json = await r.json().catch(() => null)
  if (!r.ok) {
    const detalle = Array.isArray(json?.detail) ? 'Revisa los datos ingresados' : json?.detail
    throw new ErrorApi(r.status, detalle)
  }
  return json
}
