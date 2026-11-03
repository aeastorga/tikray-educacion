import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

test('el director ve el resumen del colegio al entrar', async ({ page }) => {
  const { director: d } = semilla()
  await page.goto('/personal')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { name: /^Bienvenido/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Asistencia de hoy' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Cuaderno de control' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Familias y avisos' })).toBeVisible()
  await expect(page.getByText('apoderados con cuenta activa')).toBeVisible()
  await page.getByRole('link', { name: /pendientes de aprobar/ }).click()
  await expect(page).toHaveURL(/\/panel\/cuaderno/)
})
