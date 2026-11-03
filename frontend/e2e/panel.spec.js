import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

test('el director ve el resumen del colegio al entrar', async ({ page }) => {
  const { director: d } = semilla()
  await page.goto('/personal')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ingreso de hoy' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Avisos a familias' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Cuaderno de control' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Accesos rápidos' })).toBeVisible()
  await expect(page.getByText(/apoderados? no activ/)).toBeVisible()
  await page.getByRole('link', { name: /Justificaciones por revisar/ }).click()
  await expect(page).toHaveURL(/\/panel\/cuaderno/)
})

test('el menú lateral se abre en el celular y no hay scroll horizontal', async ({ page }) => {
  const { director: d } = semilla()
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
