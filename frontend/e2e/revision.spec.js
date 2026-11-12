import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Revisión de pantallas a 390 px, en claro y oscuro: nada se sale del ancho (ni recortado: la página tiene
// overflow-x oculto, así que se mide cada elemento) y la consola no muestra errores.
const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))
const PANEL = ['/panel', '/panel/asistencia', '/panel/asistencia/personal', '/panel/asistencia/porteria',
  '/panel/cuaderno', '/panel/cuaderno/escribir', '/panel/calendario', '/panel/autorizaciones',
  '/panel/autorizaciones/nueva', '/panel/caja', '/panel/caja/pagos', '/panel/caja/gastos', '/panel/pensiones',
  '/panel/pensiones/descuentos', '/panel/padron', '/panel/padron/anios', '/panel/padron/estructura',
  '/panel/padron/importar', '/panel/padron?alumno=1', '/panel/familias', '/panel/reunion', '/panel/personal',
  '/panel/configuracion', '/panel/configuracion/avisos']
const FAMILIA = ['/familia', '/familia/asistencia', '/familia/cuaderno', '/familia/cuaderno/nuevo/justificacion',
  '/familia/cuaderno/nuevo/permiso', '/familia/calendario', '/familia/autorizaciones', '/familia/pagos',
  '/familia/recojo', '/familia/perfil']

// Elementos que pasan el borde derecho sin estar dentro de algo que se desliza por su cuenta (pestañas, tablas).
const salidos = (page) => page.evaluate(() => {
  const ancho = document.documentElement.clientWidth
  const fuera = []
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.right <= ancho + 1 || getComputedStyle(el).position === 'fixed') continue
    let contenido = false
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      if (getComputedStyle(a).overflowX !== 'visible') { contenido = true; break }
    }
    if (!contenido && !fuera.some((f) => f.contains(el))) fuera.push(el)
  }
  return fuera.slice(0, 5).map((el) => `${el.tagName.toLowerCase()}.${[...el.classList].join('.')} → ${Math.round(el.getBoundingClientRect().right)} px`)
})

function consola(page) {
  const errores = []
  page.on('console', (m) => { if (m.type() === 'error') errores.push(m.text()) })
  page.on('pageerror', (e) => errores.push(e.message))
  return errores
}

async function recorrer(page, rutas, errores) {
  for (const ruta of rutas) {
    errores.length = 0
    await page.goto(ruta)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.cargando')).toHaveCount(0)
    expect(await salidos(page), `${ruta}: nada se sale del ancho`).toEqual([])
    expect(errores, `${ruta}: sin errores en la consola`).toEqual([])
  }
}

for (const tema of ['light', 'dark']) {
  test.describe(`a 390 px, tema ${tema === 'light' ? 'claro' : 'oscuro'}`, () => {
    test.use({ viewport: { width: 390, height: 844 }, colorScheme: tema })

    test('el panel del colegio', async ({ page }) => {
      test.setTimeout(180000)
      const errores = consola(page)
      const { administrador: d } = semilla()
      await page.goto('/personal')
      await page.getByLabel('Usuario (DNI)').fill(d.usuario)
      await page.getByLabel('Clave').fill(d.clave)
      await page.getByRole('button', { name: 'Ingresar' }).click()
      await page.waitForURL((u) => u.pathname.startsWith('/panel'))
      await recorrer(page, PANEL, errores)
    })

    test('la app de la familia', async ({ page }) => {
      test.setTimeout(120000)
      const errores = consola(page)
      const { familia: f } = semilla()
      await page.goto('/familia')
      await page.getByLabel('DNI o carné de extranjería').fill(f.documento)
      await page.getByLabel('PIN (6 números)').fill(f.pin)
      await page.getByRole('button', { name: 'Ingresar', exact: true }).click()
      await expect(page.locator('.en-vivo')).toBeVisible()
      await recorrer(page, FAMILIA, errores)
    })
  })
}

test.describe('enviar un formulario', () => {
  test.use({ viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false })

  test('muestra que está procesando y un doble clic lo manda una sola vez', async ({ page }) => {
    const { administrador: d } = semilla()
    await page.goto('/personal?volver=/panel/configuracion/perfil')
    await page.getByLabel('Usuario (DNI)').fill(d.usuario)
    await page.getByLabel('Clave').fill(d.clave)
    await page.getByRole('button', { name: 'Ingresar' }).click()
    await page.waitForURL((u) => u.pathname.startsWith('/panel'))
    const boton = page.getByRole('button', { name: 'Guardar perfil' })
    await expect(boton).toBeVisible()
    let envios = 0
    await page.route('**/api/configuracion/perfil', async (ruta) => {
      if (ruta.request().method() !== 'PUT') return ruta.continue()
      envios++
      await new Promise((r) => setTimeout(r, 600))  // servidor lento: se ve el "procesando"
      return ruta.continue()
    })
    await boton.dblclick()
    await expect(boton).toHaveAttribute('aria-busy', 'true')
    await expect(page.getByText('Perfil guardado')).toBeVisible()
    await expect(boton).not.toHaveAttribute('aria-busy')
    expect(envios).toBe(1)
  })
})
