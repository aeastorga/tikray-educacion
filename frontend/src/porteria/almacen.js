// Lo que la portería guarda en el celular para seguir marcando sin internet:
// las marcaciones aún no enviadas y el último padrón descargado. IndexedDB es
// por origen, así que cada colegio (subdominio) tiene el suyo.

const BASE = 'tikray-porteria'
let conexion = null

function abrir() {
  conexion ??= new Promise((ok, mal) => {
    const r = indexedDB.open(BASE, 1)
    r.onupgradeneeded = () => {
      r.result.createObjectStore('pendientes', { keyPath: 'id_cliente' })
      r.result.createObjectStore('datos')
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

export const datos = {
  leer: (clave) => operar('datos', 'readonly', (s) => s.get(clave)),
  guardar: (clave, valor) => operar('datos', 'readwrite', (s) => s.put(valor, clave)),
}

export function nuevoId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
}
