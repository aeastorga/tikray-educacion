// Color de acento del colegio: el principal que eligió el director. Para botones y fondos con texto
// blanco se oscurece hasta llegar a contraste 4.5:1 (WCAG AA); la versión suave es el mismo color al 9 %.

const POR_DEFECTO = '#1F4E79'

function rgb(hex) {
  const h = /^#[0-9a-f]{6}$/i.test(hex || '') ? hex.slice(1) : POR_DEFECTO.slice(1)
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}

const hex = (c) => `#${c.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('')}`.toUpperCase()

function luminancia(c) {
  const [r, g, b] = c.map((x) => {
    const v = x / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contraste(a, b) {
  const [x, y] = [luminancia(rgb(a)), luminancia(rgb(b))].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

// Oscurece de a poco (mismo tono) hasta que el blanco se lea bien encima.
export function paraTextoBlanco(color) {
  let c = rgb(color)
  for (let i = 0; i < 40 && contraste(hex(c), '#FFFFFF') < 4.5; i++) c = c.map((x) => x * 0.94)
  return hex(c)
}

export function aplicarTema(imagen) {
  const raiz = document.documentElement.style
  const acento = hex(rgb(imagen.color_primario))
  const [r, g, b] = rgb(acento)
  raiz.setProperty('--acento', acento)
  raiz.setProperty('--acento-fuerte', paraTextoBlanco(acento))
  raiz.setProperty('--acento-suave', `rgba(${r}, ${g}, ${b}, 0.09)`)
  raiz.setProperty('--acento-medio', `rgba(${r}, ${g}, ${b}, 0.18)`)
  // Nombres de antes, que aún usan algunos estilos de módulos.
  raiz.setProperty('--primario', paraTextoBlanco(acento))
  raiz.setProperty('--secundario', imagen.color_secundario)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', paraTextoBlanco(acento))
}

export function iniciales(nombre = '') {
  const partes = nombre.split(/\s+/).filter((p) => p.length > 2)
  return (partes.length ? partes : nombre.split(/\s+/)).slice(0, 2).map((p) => p[0] || '').join('').toUpperCase()
}

// Fecha y hora siempre en Lima, sin importar dónde esté el equipo.
export const LIMA = 'America/Lima'

export function horaLima(d = new Date()) {
  return Number(d.toLocaleString('en-US', { timeZone: LIMA, hour: 'numeric', hour12: false })) % 24
}

export function saludo(d = new Date()) {
  const h = horaLima(d)
  return h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches'
}

// "07:38" → "7:38 a. m."
export function hora12(hhmm) {
  if (!hhmm) return ''
  const [h, m] = hhmm.split(':').map(Number)
  // Espacios que no se cortan: "7:38 a. m." nunca queda partido en dos líneas.
  return `${h % 12 || 12}:${String(m).padStart(2, '0')}\u00A0${h < 12 ? 'a.\u00A0m.' : 'p.\u00A0m.'}`
}
