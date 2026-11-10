// Lo que la portería guarda en el celular para seguir marcando sin internet:
// las marcaciones aún no enviadas (y quién recogió a cada alumno) y el último padrón descargado. IndexedDB es
// por origen, así que cada colegio (subdominio) tiene el suyo.

const BASE = 'tikray-porteria'
let conexion = null

function abrir() {
  conexion ??= new Promise((ok, mal) => {
    const r = indexedDB.open(BASE, 2)
    r.onupgradeneeded = () => {
      const tiendas = r.result.objectStoreNames
      if (!tiendas.contains('pendientes')) r.result.createObjectStore('pendientes', { keyPath: 'id_cliente' })
      if (!tiendas.contains('datos')) r.result.createObjectStore('datos')
      // Recojo seguro: quién recogió al alumno en una salida, por enviar (uno por marcación).
      if (!tiendas.contains('recojos')) r.result.createObjectStore('recojos', { keyPath: 'marcacion' })
    }
    r.onsuccess = () => ok(r.result)
    r.onerror = () => { conexion = null; mal(r.error) }
  })
  return conexion
}

async function operar(tienda, modo, fn) {
  const db = await abrir()
  return new Promise((ok, mal) => {
    const t = db.transaction(tienda, modo)
    const pedido = fn(t.objectStore(tienda))
    t.oncomplete = () => ok(pedido?.result)
    t.onerror = () => mal(t.error)
  })
}

export const pendientes = {
  todos: () => operar('pendientes', 'readonly', (s) => s.getAll()),
  agregar: (marca) => operar('pendientes', 'readwrite', (s) => s.put(marca)),
  quitar: (ids) => operar('pendientes', 'readwrite', (s) => { ids.forEach((id) => s.delete(id)) }),
}

export const recojos = {
  todos: () => operar('recojos', 'readonly', (s) => s.getAll()),
  agregar: (r) => operar('recojos', 'readwrite', (s) => s.put(r)),
  quitar: (ids) => operar('recojos', 'readwrite', (s) => { ids.forEach((id) => s.delete(id)) }),
}

export const datos = {
  leer: (clave) => operar('datos', 'readonly', (s) => s.get(clave)),
  guardar: (clave, valor) => operar('datos', 'readwrite', (s) => s.put(valor, clave)),
}

// Al cerrar sesión: fuera el padrón (nombres de alumnos y personal) y el historial del día.
// Las marcaciones pendientes se quedan: son asistencia real que aún debe llegar al servidor.
export function borrarPadron() {
  return operar('datos', 'readwrite', (s) => { s.delete('padron'); s.delete('marcas') }).catch(() => {})
}

export function nuevoId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
}
