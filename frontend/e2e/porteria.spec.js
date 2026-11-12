import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))
const PORTERIA = '/panel/asistencia/porteria'

// Lo guardado por la portería en el celular (IndexedDB): ¿hay padrón? ¿cuántas pendientes?
function almacen(page) {
  return page.evaluate(() => new Promise((ok) => {
    const r = indexedDB.open('tikray-porteria')
    r.onsuccess = () => {
      const t = r.result.transaction(['datos', 'pendientes'])
      const padron = t.objectStore('datos').get('padron')
      const pendientes = t.objectStore('pendientes').getAll()
      t.oncomplete = () => ok({ padron: Boolean(padron.result), pendientes: pendientes.result.length })
    }
  }))
}

async function ingresar(page) {
  const { administrador } = semilla()
  await page.getByLabel('Usuario (DNI)').fill(administrador.usuario)
  await page.getByLabel('Clave').fill(administrador.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
}

async function abrirPorteria(page) {
  await page.goto(`/personal?volver=${PORTERIA}`)
  await ingresar(page)
  await expect(page.getByText('Todo enviado')).toBeVisible()
}

async function marcar(page, alumno) {
  const lector = page.getByLabel('Lector de carnets')
  await lector.fill(`TK1:${alumno.codigo}`)
  await lector.press('Enter')
  await expect(page.locator('.porteria-tarjeta')).toContainText(alumno.nombre)
}

async function sinInternet(page, context) {
  await context.setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
}

async function conInternet(page, context) {
  await context.setOffline(false)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
}

test('marca sin internet y envía al volver la conexión', async ({ page, context }) => {
  const [lucia, diego] = semilla().alumnos
  await abrirPorteria(page)
  await sinInternet(page, context)
  await expect(page.getByText('Sin internet: las marcaciones se guardan en este celular')).toBeVisible()
  await marcar(page, lucia)
  await expect(page.locator('.porteria-tarjeta')).toContainText('Entrada')
  // Sin carnet, buscando por nombre.
  await page.getByPlaceholder('Busca por apellido o nombre').fill('huaman')
  await page.locator('.porteria-busqueda li', { hasText: diego.nombre }).getByRole('button', { name: 'Marcar' }).click()
  await page.getByRole('alertdialog', { name: 'Marcar sin carnet' }).getByRole('button', { name: 'Marcar' }).click()  // un toque
  await expect(page.getByText('2 por enviar')).toBeVisible()
  expect((await almacen(page)).pendientes).toBe(2)

  await conInternet(page, context)
  await expect(page.getByText('Todo enviado')).toBeVisible({ timeout: 15000 })
  expect((await almacen(page)).pendientes).toBe(0)
  // El servidor las tiene: aparecen en las marcaciones del día.
  const marcas = await page.evaluate(async () => (await fetch('/api/asistencia/marcaciones', {
    headers: { Authorization: `Bearer ${localStorage.getItem('tikray.token')}` } })).json())
  expect(marcas.map((m) => m.nombre)).toEqual(expect.arrayContaining([lucia.nombre, diego.nombre]))
  expect(marcas.find((m) => m.nombre === diego.nombre).origen).toBe('manual')
})

test('sesión vencida: avisa, conserva las pendientes y las envía al reingresar', async ({ page }) => {
  const [, , ana] = semilla().alumnos
  await abrirPorteria(page)
  // Otra persona cierra todas las sesiones del administrador: el token deja de servir.
  await page.evaluate(() => fetch('/api/auth/cerrar-sesiones', {
    method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('tikray.token')}` } }))
  await marcar(page, ana)
  const aviso = page.getByRole('alert')
  await expect(aviso).toContainText('Sesión vencida: vuelve a ingresar')
  await expect(aviso).toContainText('La marcación pendiente está guardada')
  await expect(page).toHaveURL(new RegExp(`${PORTERIA}$`))
  expect((await almacen(page)).pendientes).toBe(1)

  await page.getByRole('link', { name: 'Ingresar de nuevo' }).click()
  await ingresar(page)
  await expect(page).toHaveURL(new RegExp(`${PORTERIA}$`))
  await expect(page.getByText('Todo enviado')).toBeVisible({ timeout: 15000 })
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect((await almacen(page)).pendientes).toBe(0)
})

test('cerrar sesión borra el padrón del celular pero no las pendientes', async ({ page, context }) => {
  const [lucia] = semilla().alumnos
  await abrirPorteria(page)
  await sinInternet(page, context)
  await marcar(page, lucia)
  await expect(page.getByText('1 por enviar')).toBeVisible()
  expect(await almacen(page)).toEqual({ padron: true, pendientes: 1 })

  await page.getByRole('button', { name: 'Abrir menú' }).click()
  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  await expect(page.getByRole('link', { name: 'Soy personal del colegio' })).toBeVisible()
  await expect.poll(() => almacen(page)).toEqual({ padron: false, pendientes: 1 })

  await context.setOffline(false)
  await abrirPorteria(page)
  expect(await almacen(page)).toEqual({ padron: true, pendientes: 0 })
})
