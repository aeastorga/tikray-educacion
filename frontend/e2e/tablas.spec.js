import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Tablas, menús de acciones, paginación y campana: el mismo diseño en todo el panel.
const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

async function director(page, volver = '/panel') {
  const { director: d } = semilla()
  await page.goto(`/personal?volver=${volver}`)
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('button', { name: 'Ingresar' })).toBeHidden()
}

test.describe('en pantalla ancha', () => {
  test.use({ viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false })

  test('Cuentas de padres pagina de 25 en 25', async ({ page }) => {
    await director(page, '/panel/familias')
    await expect(page.getByRole('heading', { name: 'Cuentas de padres' })).toBeVisible()
    const pag = page.getByRole('navigation', { name: 'Páginas' })
    await expect(pag).toContainText(/1–25 de 3\d/)  // 31 de la semilla y los que crean las otras pruebas
    await expect(page.getByRole('table', { name: 'Apoderados' }).locator('tbody tr')).toHaveCount(25)
    await pag.getByRole('button', { name: 'Página siguiente' }).click()
    await expect(pag).toContainText(/26–3\d de 3\d/)
    await expect(pag).toContainText('Página 2 de 2')
    await expect(pag.getByRole('button', { name: 'Página siguiente' })).toBeDisabled()
  })

  test('el menú de acciones se abre, se cierra con Escape y Bloquear pide confirmación', async ({ page }) => {
    await director(page, '/panel/familias')
    const fila = page.getByRole('row', { name: /Zeta 00/ })
    await expect(fila.getByRole('button', { name: 'Enviar enlace' })).toBeVisible()
    const mas = fila.getByRole('button', { name: /^Más acciones/ })
    await mas.click()
    const menu = page.getByRole('menu', { name: 'Más acciones' })
    await expect(menu).toBeVisible()
    await expect(menu.getByRole('menuitem').first()).toBeFocused()
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Escape')
    await expect(menu).toBeHidden()
    await expect(mas).toBeFocused()

    await mas.click()
    const bloquear = menu.getByRole('menuitem', { name: 'Bloquear' })
    await expect(menu.getByRole('menuitem').last()).toHaveText('Bloquear')  // la peligrosa, al final
    let pregunta = null
    page.once('dialog', (d) => { pregunta = d.message(); d.dismiss() })
    await bloquear.click()
    await expect.poll(() => pregunta).toMatch(/Bloquear/)
    await expect(menu).toBeHidden()
    await expect(fila.getByText('Sin cuenta')).toBeVisible()  // no se bloqueó: se canceló
  })

  test('la campana dice "1 respuesta" en singular', async ({ browser }) => {
    const { familia: f } = semilla()
    const colegio = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
    await director(colegio, '/panel/cuaderno/escribir')
    await colegio.getByLabel('Asunto').fill('Feria de ciencias')
    await colegio.getByRole('button', { name: 'Enviar' }).click()
    await expect(colegio.getByRole('heading', { name: 'Feria de ciencias' })).toBeVisible()

    const casa = await (await browser.newContext()).newPage()
    await casa.goto('/familia')
    await casa.getByLabel('DNI o carné de extranjería').fill(f.documento)
    await casa.getByLabel('PIN (6 números)').fill(f.pin)
    await casa.getByRole('button', { name: 'Ingresar', exact: true }).click()
    await casa.getByRole('navigation', { name: 'Secciones' }).getByRole('link', { name: /^Cuaderno/ }).click()
    await casa.getByRole('link', { name: /Feria de ciencias/ }).click()
    await casa.getByRole('button', { name: 'Firmar: leí el comunicado' }).click()  // sin pendientes para las demás pruebas
    await expect(casa.getByText(/Firmaste el/)).toBeVisible()
    await casa.getByPlaceholder('Escribe al colegio').fill('¿A qué hora empieza?')
    await casa.getByRole('button', { name: 'Enviar' }).click()
    await expect(casa.locator('.hilo')).toContainText('¿A qué hora empieza?')

    await colegio.goto('/panel')
    await colegio.getByRole('button', { name: /^Pendientes/ }).click()
    const lista = colegio.getByRole('dialog', { name: 'Pendientes' })
    await expect(lista.getByRole('link', { name: /1 respuesta de una familia/ })).toBeVisible()
    await expect(lista).not.toContainText('respuestas')
    await lista.getByRole('link', { name: /1 respuesta de una familia/ }).click()
    await expect(colegio).toHaveURL(/\/panel\/cuaderno\?pendientes=1/)
    await expect(colegio.getByLabel('Solo lo que espera al colegio')).toBeChecked()

    // Se responde: la campana queda al día para las demás pruebas.
    await colegio.getByRole('row', { name: /Feria de ciencias/ }).click()
    await colegio.getByPlaceholder('Responder a la familia').fill('A las 9.')
    await colegio.getByRole('button', { name: 'Responder' }).click()
    await expect(colegio.locator('.hilo')).toContainText('A las 9.')
  })

  test('Reunión agrupa por nivel y las recientes llevan el nivel', async ({ page }) => {
    await director(page, '/panel/reunion')
    await expect(page.getByRole('heading', { name: 'Reunión de padres' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Primaria', level: 3 })).toBeVisible()
    const abrir = page.getByRole('button', { name: 'Abrir reunión' })
    if (await abrir.isVisible()) {
      await abrir.click()
      await expect(page.getByRole('img', { name: /QR de la reunión/ })).toBeVisible()
      await page.getByRole('link', { name: 'Reuniones' }).click()
    }
    const recientes = page.getByRole('table', { name: 'Reuniones recientes' })
    await expect(recientes).toContainText('Primaria · 1° A')
    await expect(recientes.getByText(/^(Abierta|Cerrada|Vencida)$/).first()).toBeVisible()
  })
})

test('a 390 px cada fila es una tarjeta y la página no se desliza', async ({ browser }) => {
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage()
  await director(page, '/panel/familias')
  const fila = page.getByRole('table', { name: 'Apoderados' }).locator('tbody tr').first()
  await expect(fila).toBeVisible()
  expect(await fila.evaluate((tr) => getComputedStyle(tr).display)).not.toBe('table-row')
  expect(await page.locator('table.tabla thead').evaluate((t) => getComputedStyle(t).position)).toBe('absolute')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  for (const ruta of ['/panel/padron', '/panel/cuaderno', '/panel/asistencia', '/panel/reunion']) {
    await page.goto(ruta)
    await expect(page.getByRole('main').locator('h2').first()).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth), ruta).toBeLessThanOrEqual(390)
  }
})
