import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

test('reunión de padres: el padre llena su ficha, el tutor la aprueba y el padre crea su PIN', async ({ browser }) => {
  // El tutor (aquí la directora) abre la reunión de 1° A.
  const tutor = await (await browser.newContext()).newPage()
  const { director: d } = semilla()
  await tutor.goto('/personal?volver=/panel/reunion')
  await tutor.getByLabel('Usuario (DNI)').fill(d.usuario)
  await tutor.getByLabel('Clave').fill(d.clave)
  await tutor.getByRole('button', { name: 'Ingresar' }).click()
  await tutor.getByRole('button', { name: 'Abrir reunión' }).click()
  await expect(tutor.getByRole('img', { name: /QR de la reunión de 1° A/ })).toBeVisible()
  const quiosco = await tutor.getByRole('link', { name: /modo quiosco/ }).getAttribute('href')
  const qr = quiosco.replace('?quiosco=1', '')

  // El padre escanea el QR con su celular.
  const padre = await (await browser.newContext()).newPage()
  await padre.goto(qr)
  await expect(padre).not.toHaveURL(/#/)  // el código sale de la barra de direcciones
  await padre.getByLabel(/DNI de tu hijo/).fill('99999999')
  await padre.getByRole('button', { name: 'Continuar' }).click()
  await expect(padre.getByText(/No encontramos a un alumno de esta aula/)).toBeVisible()
  await padre.getByLabel(/DNI de tu hijo/).fill('79000002')
  await padre.getByRole('button', { name: 'Continuar' }).click()
  await expect(padre.getByRole('heading', { name: 'Ficha del apoderado de Ana R.' })).toBeVisible()
  const datos = padre.getByRole('group', { name: 'Tus datos' })
  await datos.getByLabel('Número de documento').fill('45678901')
  await datos.getByLabel('Nombres').fill('Carlos')
  await datos.getByLabel('Apellidos').fill('Rojas Vega')
  await datos.getByLabel('Celular').fill('987 111 222')
  await datos.getByLabel('Parentesco').selectOption('Padre')
  await padre.getByLabel(/Acepto el tratamiento/).check()
  await padre.getByRole('button', { name: 'Enviar ficha' }).click()
  await expect(padre.getByRole('heading', { name: 'Tu ficha llegó al tutor' })).toBeVisible()

  // Llega en vivo a la pantalla del tutor, marcada como nueva en el padrón.
  const ficha = tutor.locator('article.ficha-reunion')
  await expect(ficha).toContainText('ROJAS PAREDES, Ana', { timeout: 10000 })
  await expect(ficha).toContainText('Nuevo en el padrón')
  // Apoderado nuevo: sin ver su DNI en persona no se puede aprobar.
  await expect(ficha.getByRole('button', { name: 'Aprobar' })).toBeDisabled()
  await ficha.getByLabel(/Verifiqué su DNI en persona/).check()
  await ficha.getByRole('button', { name: 'Aprobar' }).click()
  await expect(tutor.getByRole('heading', { name: 'Revisadas' })).toBeVisible()
  await expect(tutor.getByText(/DNI verificado por Directora Pruebas/)).toBeVisible()

  // El celular del padre cambia solo: crea su PIN y entra.
  await expect(padre.getByRole('heading', { name: /Ficha aprobada, Carlos/ })).toBeVisible({ timeout: 10000 })
  await padre.getByLabel(/Crea tu PIN/).fill('274815')
  await padre.getByLabel('Repite el PIN').fill('274815')
  await padre.getByRole('button', { name: 'Activar mi cuenta' }).click()
  await expect(padre).toHaveURL(/\/familia$/)
  await expect(padre.getByText('Ana')).toBeVisible()

  // Quién faltó: los otros dos alumnos del aula.
  await tutor.getByRole('button', { name: 'Quién faltó' }).click()
  await expect(tutor.locator('.lista-faltan > li')).toHaveCount(2)
})
