import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

async function director(page, volver = '/panel/configuracion') {
  const { director: d } = semilla()
  await page.goto(`/personal?volver=${volver}`)
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { name: volver === '/panel/historial' ? 'Historial de actividad' : 'Configuración' })).toBeVisible()
}

// Mañana a las 9:00, hora de Lima, como lo pide un datetime-local.
function mananaLima() {
  const d = new Date(Date.now() + 24 * 3600 * 1000).toLocaleDateString('en-CA', { timeZone: 'America/Lima' })
  return `${d}T09:00`
}

// En celular el menú está detrás del botón: se abre, se mira y se cierra.
async function enMenu(page, nombre) {
  await page.getByRole('button', { name: 'Abrir menú' }).click()
  const n = await page.getByRole('navigation', { name: 'Menú principal' }).getByRole('link', { name: nombre }).count()
  await page.keyboard.press('Escape')
  return n
}

test('perfil, módulos y avisos del colegio', async ({ page }) => {
  await director(page)
  await page.getByRole('link', { name: 'Perfil' }).click()
  await page.getByLabel('Estatal').check()
  await page.getByLabel('UGEL').fill('UGEL 03')
  await page.getByLabel('Código modular').fill('0123456')
  await page.getByRole('button', { name: 'Guardar perfil' }).click()
  await expect(page.getByText('Perfil guardado')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('UGEL')).toHaveValue('UGEL 03')
  await expect(page.getByLabel('Estatal')).toBeChecked()

  // Apagar el cuaderno lo saca del menú; prenderlo lo devuelve.
  await page.getByRole('link', { name: 'Módulos' }).click()
  expect(await enMenu(page, /Cuaderno de control/)).toBe(1)
  await page.getByRole('switch', { name: 'Cuaderno de control' }).click()
  await expect(page.getByText('Módulos guardados')).toBeVisible()
  await expect(page.getByRole('switch', { name: 'Cuaderno de control' })).not.toBeChecked()
  await expect.poll(() => enMenu(page, /Cuaderno de control/)).toBe(0)
  await page.getByRole('switch', { name: 'Cuaderno de control' }).click()
  await expect(page.getByRole('switch', { name: 'Cuaderno de control' })).toBeChecked()
  await expect.poll(() => enMenu(page, /Cuaderno de control/)).toBe(1)

  await page.getByRole('link', { name: 'Avisos' }).click()
  await page.getByLabel('Desde').fill('22:00')
  await page.getByRole('button', { name: 'Guardar horario' }).click()
  await expect(page.getByText('Horario guardado')).toBeVisible()
})

test('plantilla en "Escribir" y comunicado programado que se cancela', async ({ page }) => {
  await director(page)
  await page.getByRole('link', { name: 'Plantillas' }).click()
  await page.getByRole('button', { name: 'Nueva plantilla' }).click()
  await page.getByLabel('Nombre de la plantilla').fill('Simulacro')
  await page.getByLabel('Asunto').fill('Simulacro de sismo')
  await page.getByLabel('Texto').fill('El jueves a las 10 a. m.')
  await page.getByRole('button', { name: 'Crear plantilla' }).click()
  await expect(page.locator('.lista-plantillas')).toContainText('Simulacro de sismo')

  await page.goto('/panel/cuaderno/escribir')
  await page.getByLabel('Plantilla').selectOption({ label: 'Simulacro' })
  await expect(page.getByLabel('Asunto')).toHaveValue('Simulacro de sismo')
  await expect(page.getByLabel('Detalle')).toHaveValue('El jueves a las 10 a. m.')
  await page.getByLabel('Programar el envío').check()
  await page.getByLabel('Sale el (hora de Lima)').fill(mananaLima())
  await page.getByRole('button', { name: 'Programar' }).click()
  await expect(page.getByText(/Programado para el/)).toBeVisible()

  await page.getByRole('button', { name: 'Bandeja' }).click()
  const fila = page.getByRole('row', { name: /Simulacro de sismo/ })
  await expect(fila.getByText('Programado')).toBeVisible()
  await fila.click()
  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: 'Cancelar envío' }).click()
  await expect(page.getByRole('link', { name: 'Bandeja' })).toBeVisible()
  await expect(page.getByRole('row', { name: /Simulacro de sismo/ })).toHaveCount(0)
})

test('incidencia con categoría de mérito: la familia la ve en verde', async ({ browser }) => {
  const { alumnos, familia: f } = semilla()
  const colegio = await (await browser.newContext()).newPage()
  await director(colegio)
  await colegio.getByRole('link', { name: 'Categorías' }).click()
  await expect(colegio.getByRole('heading', { name: 'Méritos' })).toBeVisible()
  await colegio.getByLabel('Nueva categoría de méritos').fill('Deportes')
  await colegio.getByRole('button', { name: 'Agregar' }).first().click()
  await expect(colegio.locator('.categorias.merito')).toContainText('Deportes')

  await colegio.goto('/panel/cuaderno/escribir')
  await colegio.getByLabel('Tipo').selectOption('incidencia')
  await colegio.getByPlaceholder('Buscar alumno por nombre o DNI').fill(alumnos[0].nombre.split(',')[0])
  await colegio.getByRole('button', { name: alumnos[0].nombre }).click()
  await colegio.getByLabel('Categoría').selectOption({ label: 'Deportes' })
  await colegio.getByLabel('Asunto').fill('Ganó la carrera de 100 metros')
  await colegio.getByRole('button', { name: 'Enviar' }).click()
  await expect(colegio.getByRole('heading', { name: 'Ganó la carrera de 100 metros' })).toBeVisible()

  const casa = await (await browser.newContext()).newPage()
  await casa.goto('/familia')
  await casa.getByLabel('DNI o carné de extranjería').fill(f.documento)
  await casa.getByLabel('PIN (6 números)').fill(f.pin)
  await casa.getByRole('button', { name: 'Ingresar', exact: true }).click()
  await casa.getByRole('navigation', { name: 'Secciones' }).getByRole('link', { name: /^Cuaderno/ }).click()
  const item = casa.locator('.lista-cuaderno li', { hasText: 'Ganó la carrera' })
  await expect(item).toHaveClass(/merito/)
  await expect(item).toContainText('Deportes')
  await item.getByRole('link').click()
  await expect(casa.getByText(/¡Un mérito para/)).toBeVisible()
  await casa.getByRole('button', { name: 'Enterado' }).click()  // no deja pendientes para las demás pruebas
  await expect(casa.getByText(/Marcaste enterado/)).toBeVisible()

  // Usada: no se borra, se desactiva (y así las demás pruebas no la necesitan).
  await colegio.goto('/panel/configuracion/categorias')
  const deportes = colegio.locator('.lista-categorias li', { hasText: 'Deportes' })
  await expect(deportes).toContainText('1 uso')
  await deportes.getByRole('button', { name: 'Desactivar' }).click()
  await expect(deportes).toContainText('Desactivada')
})

test('historial: solo el director, con filtros', async ({ page }) => {
  await director(page, '/panel/historial')
  expect(await enMenu(page, 'Historial')).toBe(1)
  await expect(page.locator('.lista-historial li').first()).toBeVisible()
  await page.getByLabel('Módulo').selectOption({ label: 'Configuración' })
  await expect(page.locator('.lista-historial')).toContainText('Perfil del colegio')
  await expect(page.locator('.lista-historial')).not.toContainText('Ganó la carrera')
})
