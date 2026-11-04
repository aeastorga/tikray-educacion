import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

async function director(page) {
  const { director: d } = semilla()
  await page.goto('/personal?volver=/panel/cuaderno')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('link', { name: 'Bandeja' })).toBeVisible()
}

async function familia(page) {
  const { familia: f } = semilla()
  await page.goto('/familia')
  await page.getByLabel('DNI o carné de extranjería').fill(f.documento)
  await page.getByLabel('PIN (6 números)').fill(f.pin)
  await page.getByRole('button', { name: 'Ingresar', exact: true }).click()
  await expect(page.locator('.en-vivo')).toBeVisible()
  await page.getByRole('navigation', { name: 'Secciones' }).getByRole('link', { name: /^Cuaderno/ }).click()
  await expect(page.getByRole('heading', { name: 'Cuaderno de control' })).toBeVisible()
}

test('comunicado con firma: la familia firma y responde, el colegio ve quién firmó', async ({ browser }) => {
  const colegio = await (await browser.newContext()).newPage()
  await director(colegio)
  await colegio.getByRole('link', { name: 'Escribir' }).click()
  await colegio.getByLabel('Para').selectOption('colegio')
  await colegio.getByLabel('Asunto').fill('Paseo al museo')
  await colegio.getByLabel('Detalle').fill('Saldremos el viernes a las 9.')
  await expect(colegio.getByLabel('Pedir firma de lectura a cada apoderado')).toBeChecked()
  await colegio.getByRole('button', { name: 'Enviar' }).click()
  await expect(colegio.getByRole('heading', { name: 'Paseo al museo' })).toBeVisible()
  await expect(colegio.getByText('0 de 1 familia firmó', { exact: false })).toBeVisible()

  const casa = await (await browser.newContext()).newPage()
  await familia(casa)
  await expect(casa.getByText('Tienes 1 pendiente de firmar')).toBeVisible()
  await casa.getByRole('link', { name: /Paseo al museo/ }).click()
  await casa.getByRole('button', { name: 'Firmar: leí el comunicado' }).click()
  await expect(casa.getByText(/Firmaste el/)).toBeVisible()
  await casa.getByPlaceholder('Escribe al colegio').fill('¿Llevan lonchera?')
  await casa.getByRole('button', { name: 'Enviar' }).click()
  await expect(casa.locator('.hilo')).toContainText('¿Llevan lonchera?')

  await colegio.reload()
  await expect(colegio.getByText('1 de 1 familia firmó', { exact: false })).toBeVisible()
  await expect(colegio.locator('.hilo')).toContainText('¿Llevan lonchera?')
  await colegio.getByPlaceholder('Responder a la familia').fill('Sí, y agua.')
  await colegio.getByRole('button', { name: 'Responder' }).click()
  await casa.reload()
  await expect(casa.locator('.hilo')).toContainText('Sí, y agua.')
})

test('permiso de salida pedido por la familia y aprobado por el colegio', async ({ browser }) => {
  const casa = await (await browser.newContext()).newPage()
  await familia(casa)
  await casa.getByRole('link', { name: 'Pedir permiso de salida' }).click()
  await casa.getByLabel('Hora de salida').fill('11:30')
  await casa.getByLabel('Motivo').fill('Cita con el dentista')
  await casa.getByLabel('¿Quién lo recoge? (nombre y DNI)').fill('Rosa Mamani 41234567')
  await casa.getByRole('button', { name: 'Enviar' }).click()
  await expect(casa.getByText(/Por aprobar/)).toBeVisible()

  const colegio = await (await browser.newContext()).newPage()
  await director(colegio)
  await colegio.getByLabel('Solo lo que espera al colegio').click()
  await expect(colegio.getByLabel('Solo lo que espera al colegio')).toBeChecked()
  await colegio.getByRole('row', { name: /Cita con el dentista/ }).click()
  await expect(colegio.getByText('¿Se autoriza esta salida?')).toBeVisible()
  await colegio.getByRole('button', { name: 'Aprobar' }).click()
  await expect(colegio.getByText(/· Aprobada/)).toBeVisible()

  await casa.reload()
  await expect(casa.getByText(/· Aprobada/)).toBeVisible()
})
