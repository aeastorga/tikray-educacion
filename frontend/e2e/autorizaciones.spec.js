import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

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

// Fecha de Lima dentro de `dias` días (AAAA-MM-DD).
const enDias = (dias) => new Date(Date.now() + dias * 86400000).toLocaleDateString('en-CA', { timeZone: 'America/Lima' })

test('el colegio pide una autorización, la familia responde y la cambia, y el colegio ve quién respondió', async ({ browser }) => {
  const page = await browser.newPage()
  await ingresar(page, '/panel/autorizaciones')
  await expect(page.getByRole('heading', { name: 'Autorizaciones', exact: true })).toBeVisible()

  // Nueva autorización para 1° A, publicada al guardar.
  await page.getByRole('button', { name: 'Nueva autorización' }).click()
  const form = page.locator('form.form-autorizacion')
  await form.getByLabel('Título').fill('Paseo al Parque de las Leyendas')
  await form.getByLabel('Descripción (opcional)').fill('Salida 8:30, regreso 13:00. Traer lonchera.')
  await form.getByLabel('Fecha de la actividad (opcional)').fill(enDias(6))
  await form.getByLabel('Responder hasta').fill(enDias(4))
  await form.getByLabel('Una o varias secciones').check()
  await form.getByLabel('1° A').check()
  await form.getByRole('button', { name: 'Publicar' }).click()
  await expect(page.getByRole('heading', { name: 'Paseo al Parque de las Leyendas' })).toBeVisible()
  await expect(page.locator('.cifras')).toContainText('3Faltan')
  await page.getByRole('button', { name: 'Recordar a los que faltan' }).click()
  await expect(page.getByRole('status')).toContainText('Recordatorio enviado a 1 familia.')

  // La familia: pestaña Autorizaciones, pendiente arriba; autoriza y luego cambia a "No autorizo".
  const casa = await browser.newPage()
  await familia(casa)
  await casa.getByRole('link', { name: /Autoriza/ }).click()
  await expect(casa.getByRole('heading', { name: 'Autorizaciones' })).toBeVisible()
  const tarjeta = casa.locator('.autorizacion-familia', { hasText: 'Paseo al Parque de las Leyendas' })
  await expect(tarjeta).toContainText('Por responder')
  await tarjeta.getByLabel('Comentario (opcional)').fill('La recojo yo a la salida')
  await tarjeta.getByRole('button', { name: 'Autorizo', exact: true }).click()
  await expect(tarjeta).toContainText('Autorizado')
  await expect(tarjeta).toContainText('Usted respondió')
  await expect(tarjeta).not.toContainText('Por responder')
  await tarjeta.getByRole('button', { name: 'Cambiar respuesta' }).click()
  await tarjeta.getByRole('button', { name: 'No autorizo' }).click()
  await expect(tarjeta).toContainText('No autorizado')
  await casa.close()

  // El colegio ve la respuesta vigente, quién respondió y el cambio; descarga la lista en PDF y Excel.
  await page.reload()
  await expect(page.locator('.cifras')).toContainText('1No autorizan')
  const fila = page.getByRole('row', { name: /QUISPE MAMANI, Lucía/ })
  await expect(fila).toContainText('No autoriza')
  await expect(fila).toContainText('Rosa Mamani')
  await expect(fila).toContainText('1 cambio')
  let descarga = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Lista en PDF' }).click()
  expect((await descarga).suggestedFilename()).toMatch(/^autorizacion-\d+\.pdf$/)
  descarga = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Lista en Excel' }).click()
  expect((await descarga).suggestedFilename()).toMatch(/^autorizacion-\d+\.xlsx$/)

  // Anular: queda visible como anulada.
  await page.getByRole('button', { name: 'Anular' }).click()
  await page.getByLabel('Motivo de la anulación').fill('Se suspende por lluvia')
  await page.getByRole('button', { name: 'Anular autorización' }).click()
  await expect(page.getByRole('status')).toContainText('Anulada')
  await expect(page.locator('.aviso-anulada')).toContainText('Se suspende por lluvia')
  await page.getByRole('button', { name: '← Autorizaciones' }).click()
  await expect(page.getByRole('row', { name: /Paseo al Parque de las Leyendas/ })).toContainText('Anulada')
  await page.close()
})
