import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

test('el administrador ve el resumen del colegio al entrar', async ({ page }) => {
  const { administrador: d } = semilla()
  await page.goto('/personal')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ingreso de hoy' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Avisos a familias' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Cuaderno de control' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Accesos rápidos' })).toBeVisible()
  await expect(page.getByText(/Ningún apoderado tiene los avisos activos|apoderados? reciben? los avisos/)).toBeVisible()
  await page.getByRole('link', { name: /Justificaciones por revisar/ }).click()
  await expect(page).toHaveURL(/\/panel\/cuaderno/)
})

test('el administrador ve cuántos usuarios usa en Personal', async ({ page }) => {
  const { administrador: d } = semilla()
  await page.goto('/personal')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible()
  await page.goto('/panel/personal')
  await expect(page.getByTestId('cupo-usuarios')).toHaveText(/^Usuarios: \d+, sin límite$/)
})

test('el menú lateral se abre en el celular y no hay scroll horizontal', async ({ page }) => {
  const { administrador: d } = semilla()
  await page.goto('/personal')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  const menu = page.getByRole('navigation', { name: 'Menú principal' })
  await expect(menu).toBeHidden()
  await page.getByRole('button', { name: 'Abrir menú' }).click()
  await expect(menu.getByRole('link', { name: 'Inicio' })).toBeVisible()
  await expect(menu.getByRole('link', { name: /Portería/ })).toContainText('En vivo')
  await menu.getByRole('link', { name: 'Configuración' }).click()
  await expect(menu).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Menú lateral' })).toBeVisible()
  // Sin scroll horizontal en el celular.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('pantalla de ingreso: dos botones y el ingreso del padre con su documento y PIN', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Bienvenido' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Soy personal del colegio/ })).toBeInViewport()
  await page.getByRole('link', { name: /Soy padre o apoderado/ }).click()
  await expect(page.getByLabel('DNI o carné de extranjería')).toBeVisible()
  await page.getByRole('button', { name: 'Olvidé mi PIN' }).click()
  await expect(page.getByText(/Pida un PIN nuevo en secretaría/)).toBeVisible()
  await page.getByRole('link', { name: 'Volver' }).click()
  await expect(page).toHaveURL(/\/$/)
})

test('las fuentes vienen de la propia app, no de Google', async ({ page }) => {
  const externas = []
  page.on('request', (r) => { if (/fonts\.(googleapis|gstatic)\.com/.test(r.url())) externas.push(r.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Bienvenido' })).toBeVisible()
  const cargadas = await page.evaluate(async () => {
    await document.fonts.ready
    return [document.fonts.check('800 16px "Bricolage Grotesque"'), document.fonts.check('400 16px "Plus Jakarta Sans"')]
  })
  expect(cargadas).toEqual([true, true])
  expect(externas).toEqual([])
})

test.describe('apariencia', () => {
  test.use({ colorScheme: 'dark' }) // el celular está en modo oscuro

  test('abre en claro aunque el equipo esté en oscuro; Oscuro se aplica y se recuerda', async ({ page }) => {
    const fondo = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    const barra = () => page.locator('meta[name="theme-color"]').getAttribute('content')
    const { administrador: d } = semilla()
    await page.goto('/personal')
    await expect(page.locator('html')).toHaveAttribute('data-tema', 'claro')
    expect(await fondo()).toBe('rgb(243, 245, 249)')
    await page.getByLabel('Usuario (DNI)').fill(d.usuario)
    await page.getByLabel('Clave').fill(d.clave)
    await page.getByRole('button', { name: 'Ingresar' }).click()
    await expect(page.getByRole('heading', { name: 'Ingreso de hoy' })).toBeVisible()

    await page.getByRole('button', { name: 'Abrir menú' }).click()
    const menu = page.getByRole('group', { name: 'Apariencia' })
    await expect(menu.getByRole('radio', { name: 'Claro' })).toBeChecked()
    await menu.getByRole('radio', { name: 'Oscuro' }).check()
    await expect(page.locator('html')).toHaveAttribute('data-tema', 'oscuro')
    expect(await fondo()).toBe('rgb(11, 15, 23)')
    expect(await barra()).toBe('#0B0F17')

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Ingreso de hoy' })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-tema', 'oscuro')
    expect(await fondo()).toBe('rgb(11, 15, 23)')

    // Automático sigue al equipo (aquí, oscuro); Claro vuelve aunque el equipo siga en oscuro.
    await page.getByRole('button', { name: 'Abrir menú' }).click()
    await menu.getByRole('radio', { name: 'Automático' }).check()
    expect(await fondo()).toBe('rgb(11, 15, 23)')
    await menu.getByRole('radio', { name: 'Claro' }).check()
    expect(await fondo()).toBe('rgb(243, 245, 249)')
    expect(await barra()).not.toBe('#0B0F17')
  })
})
