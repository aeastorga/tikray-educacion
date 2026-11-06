// Textos comunes del panel: plurales, secciones con nivel, documentos y fechas en hora de Lima.

const LIMA = 'America/Lima'

// plural(1, 'respuesta', 'respuestas') → "1 respuesta"; plural(3, …) → "3 respuestas".
export function plural(n, uno, varios) {
  const numero = Number(n) || 0
  return `${numero.toLocaleString('es-PE')} ${numero === 1 ? uno : varios}`
}

// Siempre con el nivel: Inicial, Primaria y Secundaria repiten nombres. Acepta un texto ya armado
// ("Primaria · 1° A") o las partes.
export function nombreSeccion(nivel, grado, seccion) {
  if (grado === undefined && seccion === undefined) return nivel || ''
  return [nivel, [grado, seccion].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
}

// DNI 45781236 · CE 001234567 · Pasaporte AB12345. El tipo OTRO (solo la demo) es un código interno.
const TIPOS_DOCUMENTO = { DNI: 'DNI', CE: 'CE', PASAPORTE: 'Pasaporte', PAS: 'Pasaporte', OTRO: 'Código' }
export function documento(tipo, numero) {
  if (!numero) return ''
  return `${TIPOS_DOCUMENTO[tipo] || tipo || 'Doc.'} ${numero}`
}

function diaLima(fecha) {
  return fecha.toLocaleDateString('en-CA', { timeZone: LIMA })
}

// "Hoy, 8:42 a. m.", "Ayer, 4:10 p. m." o "3 nov., 8:42 a. m." (con año si no es el actual). Una sola línea.
export function fechaHora(iso) {
  if (!iso) return ''
  const f = new Date(iso)
  const hora = f.toLocaleTimeString('es-PE', { timeZone: LIMA, hour: 'numeric', minute: '2-digit' })
  const hoy = new Date()
  const ayer = new Date(hoy.getTime() - 86400000)
  let dia
  if (diaLima(f) === diaLima(hoy)) dia = 'Hoy'
  else if (diaLima(f) === diaLima(ayer)) dia = 'Ayer'
  else {
    const mismoAnio = diaLima(f).slice(0, 4) === diaLima(hoy).slice(0, 4)
    dia = f.toLocaleDateString('es-PE', { timeZone: LIMA, day: 'numeric', month: 'short', ...(mismoAnio ? {} : { year: 'numeric' }) })
  }
  return `${dia}, ${hora}`.replace(/\s/g, ' ')
}

// "hace 5 min", "hace 2 h", "hace 3 días".
export function hace(iso) {
  if (!iso) return ''
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (min < 1) return 'hace un momento'
  if (min < 60) return `hace ${min} min`
  const h = Math.round(min / 60)
  if (h < 24) return `hace ${h} h`
  return `hace ${plural(Math.round(h / 24), 'día', 'días')}`
}

export function iniciales(nombre) {
  // "Mamani Quispe, Rosa" → "RM"; "Rosa Mamani" → "RM".
  const [apellidos, nombres] = nombre.includes(',') ? nombre.split(',').map((x) => x.trim()) : [null, nombre]
  const n = (nombres || '').split(/\s+/).filter(Boolean)
  const a = (apellidos || '').split(/\s+/).filter(Boolean)
  const letras = apellidos ? [n[0], a[0]] : [n[0], n[n.length - 1]]
  return letras.filter(Boolean).map((x) => x[0]).join('').toUpperCase().slice(0, 2) || '?'
}

// "S/ 1,234.50" (con espacio que no se parte). Los montos llegan del servidor como texto con dos decimales (nunca se suman aquí en float).
export function soles(monto) {
  if (monto == null || monto === '') return ''
  const [entero, dec = '00'] = String(monto).split('.')
  const signo = entero.startsWith('-') ? '-' : ''
  return `${signo}S/\u00a0${Number(entero.replace('-', '')).toLocaleString('en-US')}.${dec.padEnd(2, '0').slice(0, 2)}`
}

// "31/03/2026" desde "2026-03-31" (una fecha de Lima, sin hora: no pasa por la zona del navegador).
export function fechaCorta(iso) {
  if (!iso) return ''
  const [a, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${a}`
}
