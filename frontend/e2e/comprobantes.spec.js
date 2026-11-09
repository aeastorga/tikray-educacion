import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

async function director(page, volver) {
  const { director: d } = semilla()
  await page.goto(`/personal?volver=${volver}`)
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
}

test('comprobantes electrónicos: el director configura sin ver el token y Caja lista los que tienen error', async ({ page }) => {
  await director(page, '/panel/configuracion/comprobantes')
  await expect(page.getByRole('heading', { name: 'Comprobantes electrónicos SUNAT' })).toBeVisible()
  await expect(page.getByText('Token: sin configurar.')).toBeVisible()

  // RUC con dígito verificador inválido: el servidor lo rechaza.
  await page.getByLabel('Emite comprobantes electrónicos').check()
  await page.getByLabel('RUC').fill('20999999991')
  await page.getByLabel('Razón social').fill('Colegio de Pruebas SAC')
  await page.getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByText(/El RUC no es válido/)).toBeVisible()

  // Válido, con token: queda "configurado" y el token no vuelve.
  await page.getByLabel('RUC').fill('20999999990')
  await page.getByLabel('Token del proveedor').fill('token-secreto-e2e')
  await page.getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByText('Comprobantes guardados')).toBeVisible()
  await expect(page.getByText('Token: configurado.')).toBeVisible()
  await expect(page.getByLabel('Token del proveedor')).toHaveValue('')
  await page.reload()
  await expect(page.getByLabel('RUC')).toHaveValue('20999999990')
  await expect(page.getByText('token-secreto-e2e')).toHaveCount(0)

  // Caja › Comprobantes: sin proveedor no hay comprobantes, la lista está vacía.
  await page.goto('/panel/caja/comprobantes')
  await expect(page.getByRole('heading', { name: 'Comprobantes con error' })).toBeVisible()
  await expect(page.getByText('Sin comprobantes con error')).toBeVisible()
  const ancho = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(ancho).toBeLessThanOrEqual(0)
})
