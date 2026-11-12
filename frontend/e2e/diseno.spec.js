import { expect, test } from '@playwright/test'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// Diseño: el panel y la app de la familia se adaptan a cualquier ancho (centrados desde 1600 px, sin
// desplazamiento de lado), y las confirmaciones usan la ventana propia, no la del navegador.
const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))
const ROJO = 'rgb(185, 28, 28)'

async function administrador(page, volver = '/panel') {
  const { administrador: d } = semilla()
  await page.goto(`/personal?volver=${volver}`)
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await page.waitForURL((u) => u.pathname.startsWith('/panel'))
  await expect(page.locator('.marco > .contenido')).toBeVisible()
}

// Desplazamiento de lado y espacio libre a cada lado del contenido (en el panel, contando desde el menú).
const medir = (page, selector) => page.evaluate((sel) => {
  const ancho = document.documentElement.clientWidth
  const marco = document.querySelector('.marco')
  const menu = marco ? parseFloat(getComputedStyle(marco).paddingLeft) : 0
  const r = document.querySelector(sel).getBoundingClientRect()
  return { desborde: document.scrollingElement.scrollWidth - ancho, disponible: ancho - menu,
    izquierda: r.left - menu, derecha: ancho - r.right, ancho: r.width }
}, selector)

const PANTALLAS = [['/panel', 'Inicio'], ['/panel/familias', 'Cuentas de padres'], ['/panel/asistencia', 'Asistencia'],
  ['/panel/pensiones', 'Pensiones']]

for (const ancho of [1024, 1920, 2560]) {
  test.describe(`panel a ${ancho} px`, () => {
    test.use({ viewport: { width: ancho, height: 900 }, isMobile: false, hasTouch: false })

    test(`Inicio, Cuentas de padres, Asistencia y Pensiones llenan el ancho y se centran desde 1600 px (${ancho} px)`, async ({ page }) => {
      await administrador(page)
      for (const [ruta, nombre] of PANTALLAS) {
        await page.goto(ruta)
        await page.waitForLoadState('networkidle')
        const m = await medir(page, '.marco > .contenido')
        expect(m.desborde, `${nombre}: sin desplazamiento de lado`).toBeLessThanOrEqual(0)
        if (m.disponible > 1600) {
          expect(m.ancho, `${nombre}: máximo 1600 px`).toBeLessThanOrEqual(1600)
          expect(Math.abs(m.izquierda - m.derecha), `${nombre}: centrado`).toBeLessThan(24)
        } else {
          expect(m.izquierda + m.derecha, `${nombre}: llena el ancho`).toBeLessThanOrEqual(1)
        }
      }
    })
  })
}

test.describe('app de la familia en PC', () => {
  test.use({ viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false })

  test('el encabezado se alinea con la columna y no hay desplazamiento de lado', async ({ page }) => {
    const { familia: f } = semilla()
    await page.goto('/familia')
    await page.getByLabel('DNI o carné de extranjería').fill(f.documento)
    await page.getByLabel('PIN (6 números)').fill(f.pin)
    await page.getByRole('button', { name: 'Ingresar', exact: true }).click()
    await expect(page.locator('.en-vivo')).toBeVisible()
    const m = await page.evaluate(() => {
      const columna = document.querySelector('.app-contenido')
      const relleno = parseFloat(getComputedStyle(columna).paddingLeft)
      const c = columna.getBoundingClientRect()
      const logo = document.querySelector('.app-cabecera').firstElementChild.getBoundingClientRect()
      return { columna: c.left + relleno, logo: logo.left, desborde: document.scrollingElement.scrollWidth - innerWidth,
        izquierda: c.left, derecha: innerWidth - c.right }
    })
    expect(m.desborde).toBeLessThanOrEqual(0)
    expect(Math.abs(m.izquierda - m.derecha)).toBeLessThan(24)
    expect(Math.abs(m.logo - m.columna)).toBeLessThan(2)
  })
})

test.describe('ventana propia en PC', () => {
  test.use({ viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false })

  test('confirmar: botón rojo, foco dentro, Escape cierra sin hacer nada y el foco vuelve', async ({ page }) => {
    await administrador(page, '/panel/familias')
    const fila = page.getByRole('row', { name: /Zeta 00/ })
    const mas = fila.getByRole('button', { name: /^Más acciones/ })
    await mas.click()
    await page.getByRole('menu', { name: 'Más acciones' }).getByRole('menuitem', { name: 'Bloquear' }).click()
    const ventana = page.getByRole('alertdialog', { name: 'Bloquear acceso' })
    await expect(ventana).toBeVisible()
    await expect(ventana).toHaveAttribute('aria-modal', 'true')
    await expect(ventana).toContainText('se cierran sus sesiones')
    const [cancelar, bloquear] = [ventana.getByRole('button', { name: 'Cancelar' }), ventana.getByRole('button', { name: 'Bloquear' })]
    expect(await bloquear.evaluate((b) => getComputedStyle(b).backgroundColor)).toBe(ROJO)  // no se puede deshacer
    await expect(cancelar).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(bloquear).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(cancelar).toBeFocused()  // el foco no sale de la ventana
    const ancho = (await ventana.boundingBox()).width
    expect(ancho).toBeGreaterThan(400)
    expect(ancho).toBeLessThanOrEqual(440)
    await page.keyboard.press('Escape')
    await expect(ventana).toBeHidden()
    await expect(mas).toBeFocused()
    await expect(fila.getByText('Sin cuenta')).toBeVisible()  // no se bloqueó
    await expect(page.locator('.ventana-fondo')).toHaveCount(0)
  })

  test('pedir motivo: no deja confirmar vacío, un clic fuera no borra lo escrito y anula con el motivo', async ({ page }) => {
    const { alumnos } = semilla()
    await administrador(page, '/panel/pensiones/descuentos')
    const r = await page.evaluate(async (alumno) => (await fetch('/api/pensiones/descuentos', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('tikray.token')}` },
      body: JSON.stringify({ alumno_id: alumno, tipo: 'monto', valor: '5', motivo: 'Prueba de la ventana' }),
    })).status, alumnos[2].id)
    expect(r).toBe(201)
    await page.reload()
    const fila = page.getByRole('row', { name: /Prueba de la ventana/ })
    await fila.getByRole('button', { name: /^Más acciones/ }).click()
    await page.getByRole('menuitem', { name: 'Anular descuento' }).click()
    const ventana = page.getByRole('dialog', { name: 'Anular descuento' })
    const motivo = ventana.getByLabel('Motivo de la anulación')
    const anular = ventana.getByRole('button', { name: 'Anular descuento' })
    await expect(motivo).toBeFocused()
    await expect(anular).toBeDisabled()
    await motivo.fill('   ')
    await expect(anular).toBeDisabled()
    await motivo.fill('no')  // el servidor pide 3 caracteres o más
    await expect(anular).toBeDisabled()
    await motivo.fill('Se dio por error')
    await expect(anular).toBeEnabled()
    await page.mouse.click(5, 5)  // fuera de la ventana: con un motivo escrito no se cierra
    await expect(ventana).toBeVisible()
    await anular.dblclick()  // doble clic: se manda una sola vez
    await expect(ventana).toBeHidden()
    await expect(fila).toContainText('Anulado')
    await expect(fila).toContainText('Se dio por error')
  })
})

test.describe('ventana propia en celular', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('sube desde abajo, a todo el ancho, con la acción arriba y botones grandes', async ({ page }) => {
    await administrador(page, '/panel/familias')
    const mas = page.getByRole('row', { name: /Zeta 00/ }).getByRole('button', { name: /^Más acciones/ })
    await mas.scrollIntoViewIfNeeded()  // el menú se cierra si la página se desplaza
    await page.waitForTimeout(300)
    await mas.click()
    await page.getByRole('menuitem', { name: 'Bloquear' }).click()
    const ventana = page.getByRole('alertdialog', { name: 'Bloquear acceso' })
    await expect(ventana).toBeVisible()
    await page.waitForTimeout(300)  // termina de subir
    const caja = await ventana.boundingBox()
    expect(Math.round(caja.width)).toBe(390)
    expect(Math.round(caja.y + caja.height)).toBe(844)
    const bloquear = await ventana.getByRole('button', { name: 'Bloquear' }).boundingBox()
    const cancelar = await ventana.getByRole('button', { name: 'Cancelar' }).boundingBox()
    expect(bloquear.y).toBeLessThan(cancelar.y)  // la acción principal arriba
    expect(bloquear.height).toBeGreaterThanOrEqual(44)
    expect(cancelar.height).toBeGreaterThanOrEqual(44)
    await ventana.getByRole('button', { name: 'Cancelar' }).click()
    await expect(ventana).toBeHidden()
  })
})

test('ningún archivo de frontend/src usa las ventanas del navegador (confirm, prompt, alert)', () => {
  const raiz = fileURLToPath(new URL('../src', import.meta.url))
  const archivos = []
  const recorrer = (d) => readdirSync(d).forEach((n) => {
    const p = join(d, n)
    if (statSync(p).isDirectory()) recorrer(p)
    else if (/\.(jsx?|tsx?)$/.test(n)) archivos.push(p)
  })
  recorrer(raiz)
  const prohibido = /(?<![\w.$])(?:window\.)?(?:confirm|prompt|alert)\s*\(/
  const encontrados = archivos.flatMap((p) => readFileSync(p, 'utf8').split('\n')
    .map((linea, i) => [linea, i + 1]).filter(([linea]) => prohibido.test(linea))
    .map(([linea, n]) => `${p.slice(raiz.length + 1)}:${n}: ${linea.trim()}`))
  expect(encontrados, 'usa useConfirmar() de espacios/comun/Dialogo.jsx').toEqual([])
})
