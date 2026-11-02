// Las mismas reglas del servidor (app/codigos.py y app/asistencia.py), para que
// la portería responda al instante aunque no haya internet. El servidor decide
// al final: lo de aquí es lo que se muestra en pantalla.

const ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
const LARGO = 8

export function leerCodigo(texto) {
  let t = (texto || '').trim().toUpperCase()
  let tipo = null
  if (t.startsWith('TK1P:')) { tipo = 'personal'; t = t.slice(5) }
  else if (t.startsWith('TK1:')) { tipo = 'alumno'; t = t.slice(4) }
  if (t.length !== LARGO || [...t].some((c) => !ALFABETO.includes(c))) return null
  return { tipo, codigo: t }
}

export function indexar(padron) {
  const alumnos = new Map(padron.alumnos.map((a) => [a.codigo, { ...a, tipo: 'alumno' }]))
  const personal = new Map(padron.personal.map((p) => [p.codigo, { ...p, tipo: 'personal' }]))
  const turnos = new Map(padron.turnos.map((t) => [t.id, t]))
  return { alumnos, personal, turnos }
}

export function buscar(indice, leido) {
  if (leido.tipo !== 'personal' && indice.alumnos.has(leido.codigo)) return indice.alumnos.get(leido.codigo)
  if (leido.tipo !== 'alumno' && indice.personal.has(leido.codigo)) return indice.personal.get(leido.codigo)
  return null
}

export function horaLima(fecha) {
  return fecha.toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/Lima' })
}

export function fechaLima(fecha) {
  return fecha.toLocaleDateString('en-CA', { timeZone: 'America/Lima' }) // AAAA-MM-DD
}

export function minutosTarde(turno, momento) {
  if (!turno) return 0
  const [h, m] = horaLima(momento).split(':').map(Number)
  const [he, me] = turno.hora_entrada.split(':').map(Number)
  const minutos = h * 60 + m - (he * 60 + me)
  return minutos > turno.tolerancia_minutos ? minutos : 0
}

// marcas: instantes (ms) ya aceptados hoy para esa persona en este celular.
export function decidir(marcas, momento, minutosDuplicado) {
  const t = momento.getTime()
  if (marcas.some((m) => Math.abs(m - t) < minutosDuplicado * 60000)) return 'duplicada'
  return marcas.length === 0 || t < Math.min(...marcas) ? 'entrada' : 'salida'
}

export function sinTildes(texto) {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}
