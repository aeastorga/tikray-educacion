import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))
const PORTERIA = '/panel/asistencia/porteria'
const token = () => localStorage.getItem('tikray.token')

async function ingresar(page, volver) {
  const { administrador } = semilla()
  await page.goto(`/personal?volver=${volver}`)
  await page.getByLabel('Usuario (DNI)').fill(administrador.usuario)
  await page.getByLabel('Clave').fill(administrador.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
}

async function familia(page) {
  const { familia: f } = semilla()
  await page.goto('/familia')
  await page.getByLabel('DNI o carné de extranjería').fill(f.documento)
  await page.getByLabel('PIN (6 números)').fill(f.pin)
  await page.getByRole('button', { name: 'Ingresar', exact: true }).click()
  await expect(page.locator('.en-vivo')).toBeVisible()
}

// Lo que la portería tiene por enviar en el celular (marcaciones y recojos).
function porEnviar(page) {
  return page.evaluate(() => new Promise((ok) => {
    const r = indexedDB.open('tikray-porteria')
    r.onsuccess = () => {
      const t = r.result.transaction(['pendientes', 'recojos'])
      const m = t.objectStore('pendientes').getAll()
      const x = t.objectStore('recojos').getAll()
      t.oncomplete = () => ok({ marcaciones: m.result.length, recojos: x.result.length })
    }
  }))
}

test('la familia agrega a quien recoge, la portería lo elige al salir (también sin internet) y la familia lo ve', async ({ browser }) => {
  const [lucia] = semilla().alumnos

  // La madre de Lucía agrega a la tía desde la app.
  const casa = await browser.newPage()
  await familia(casa)
  await casa.getByRole('button', { name: 'Quién puede recogerlos' }).click()
  await expect(casa.getByRole('heading', { name: 'Recojo seguro' })).toBeVisible()
  await casa.getByRole('button', { name: 'Agregar persona' }).click()
  await casa.getByLabel('Nombres').fill('Carmen')
  await casa.getByLabel('Apellidos').fill('Quispe Rojas')
  await casa.getByLabel('Número').fill('45678901')
  await casa.getByLabel('Parentesco').fill('Tía')
  await casa.getByRole('button', { name: 'Agregar', exact: true }).click()
  await expect(casa.locator('.recojo-personas')).toContainText('Carmen Quispe Rojas')
  await casa.close()

  // Portería: Lucía ya entró hace media hora (en el servidor y en este celular).
  const page = await browser.newPage()
  await ingresar(page, PORTERIA)
  await expect(page.getByText('Todo enviado')).toBeVisible()
  await page.evaluate(async ({ id, tk }) => {
    const momento = new Date(Date.now() - 30 * 60000)
    await fetch('/api/asistencia/marcaciones', { method: 'POST', headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${tk}` }, body: JSON.stringify({ marcaciones: [
      { id_cliente: `e2e-entrada-${id}`, alumno_id: id, momento: momento.toISOString() }] }) })
    const fecha = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Lima' })
    await new Promise((ok) => {
      const r = indexedDB.open('tikray-porteria')
      r.onsuccess = () => {
        const t = r.result.transaction('datos', 'readwrite')
        t.objectStore('datos').put({ fecha, lista: [[`alumno:${id}`, [momento.getTime()]]] }, 'marcas')
        t.oncomplete = ok
      }
    })
  }, { id: lucia.id, tk: await page.evaluate(token) })
  await page.reload()
  await expect(page.getByText('Todo enviado')).toBeVisible()

  // Sin internet: marca la salida y elige a la tía (del padrón guardado).
  await page.context().setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  const lector = page.getByLabel('Lector de carnets')
  await lector.fill(`TK1:${lucia.codigo}`)
  await lector.press('Enter')
  await expect(page.locator('.porteria-tarjeta')).toContainText('Salida')
  const panel = page.locator('.recojo-panel')
  await expect(panel.getByRole('heading', { name: '¿Quién recoge a Lucía?' })).toBeVisible()
  await expect(panel).toContainText('Rosa Mamani')
  await expect(panel).toContainText('Madre · DNI ••••4567')
  await expect(panel).not.toContainText('45678901') // el documento completo no está en el celular
  await panel.getByRole('button', { name: /Carmen Quispe Rojas/ }).click()
  await expect(panel).toContainText('Recogido por Carmen Quispe Rojas')
  await expect(page.getByText('2 por enviar')).toBeVisible()
  expect(await porEnviar(page)).toEqual({ marcaciones: 1, recojos: 1 })

  // Vuelve la conexión: sube la salida y después quién la recogió.
  await page.context().setOffline(false)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.getByText('Todo enviado')).toBeVisible({ timeout: 15000 })
  expect(await porEnviar(page)).toEqual({ marcaciones: 0, recojos: 0 })

  // En Asistencia, la salida muestra quién lo recogió.
  await page.goto('/panel/asistencia')
  const salidas = page.locator('section.detalle-seccion', { has: page.getByRole('heading', { name: 'Salidas y quién recogió a cada alumno' }) })
  await expect(salidas).toContainText(lucia.nombre)
  await expect(salidas).toContainText('Carmen Quispe Rojas (tía)')
  await salidas.getByLabel('Solo recogidos por alguien fuera de la lista').check()
  await expect(salidas).toContainText('Nadie fuera de la lista')

  // La familia lo ve en la app (sin un segundo aviso).
  const casa2 = await browser.newPage()
  await familia(casa2)
  await expect(casa2.locator('.en-vivo')).toContainText('Lo recogió Carmen Quispe Rojas (tía)')
  await casa2.close()
})

test('quien recoge no está en la lista: la salida se registra igual y queda marcada', async ({ page }) => {
  const [, diego] = semilla().alumnos
  await ingresar(page, PORTERIA)
  await expect(page.getByText('Todo enviado')).toBeVisible()
  await page.evaluate(async ({ id, tk }) => {
    const momento = new Date(Date.now() - 30 * 60000)
    await fetch('/api/asistencia/marcaciones', { method: 'POST', headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${tk}` }, body: JSON.stringify({ marcaciones: [
      { id_cliente: `e2e-entrada-${id}`, alumno_id: id, momento: momento.toISOString() }] }) })
    const fecha = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Lima' })
    await new Promise((ok) => {
      const r = indexedDB.open('tikray-porteria')
      r.onsuccess = () => {
        const t = r.result.transaction('datos', 'readwrite')
        t.objectStore('datos').put({ fecha, lista: [[`alumno:${id}`, [momento.getTime()]]] }, 'marcas')
        t.oncomplete = ok
      }
    })
  }, { id: diego.id, tk: await page.evaluate(token) })
  await page.reload()
  const lector = page.getByLabel('Lector de carnets')
  await lector.fill(`TK1:${diego.codigo}`)
  await lector.press('Enter')
  const panel = page.locator('.recojo-panel')
  await expect(panel).toContainText('No hay nadie en la lista.')
  await panel.getByRole('button', { name: 'Otra persona (no está en la lista)' }).click()
  await panel.getByLabel('Nombres').fill('Pedro')
  await panel.getByLabel('Apellidos').fill('Gómez')
  await panel.getByLabel('Número').fill('40404040')
  await panel.getByRole('button', { name: 'Registrar quién lo recoge' }).click()
  await expect(panel).toContainText('Recogido por Pedro Gómez')
  await expect(panel).toContainText('Fuera de la lista')
  await expect(page.getByText('Todo enviado')).toBeVisible({ timeout: 15000 })

  await page.goto('/panel/asistencia')
  const salidas = page.locator('section.detalle-seccion', { has: page.getByRole('heading', { name: 'Salidas y quién recogió a cada alumno' }) })
  await salidas.getByLabel('Solo recogidos por alguien fuera de la lista').check()
  await expect(salidas).toContainText(diego.nombre)
  await expect(salidas).toContainText('Pedro Gómez')
})
