import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const semilla = () => JSON.parse(readFileSync(new URL('./.semilla.json', import.meta.url)))

async function director(page) {
  const { director: d } = semilla()
  await page.goto('/personal?volver=/panel/pensiones/configuracion')
  await page.getByLabel('Usuario (DNI)').fill(d.usuario)
  await page.getByLabel('Clave').fill(d.clave)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { name: /Conceptos y cronograma/ })).toBeVisible()
}

test('pensión: concepto, cronograma, cuotas, cobro con recibo y la familia lo ve', async ({ browser }) => {
  const colegio = await (await browser.newContext()).newPage()
  await director(colegio)

  // Concepto con monto por nivel y cronograma de marzo a diciembre.
  await colegio.getByRole('button', { name: 'Concepto' }).click()
  await colegio.getByLabel('Nombre').fill('Pensión')
  await colegio.getByRole('button', { name: 'Crear' }).click()
  await expect(colegio.getByText('Concepto creado')).toBeVisible()
  await colegio.getByRole('button', { name: 'Montos' }).click()
  await colegio.getByLabel('Todo el nivel (S/)').fill('350')
  await colegio.getByRole('button', { name: 'Guardar montos' }).click()
  await expect(colegio.getByText('Montos guardados')).toBeVisible()
  await colegio.getByRole('button', { name: 'Armar por meses' }).click()
  await colegio.getByRole('button', { name: 'Armar cronograma' }).click()
  await expect(colegio.getByText('Cronograma armado')).toBeVisible()
  await colegio.getByRole('button', { name: 'Generar cuotas' }).click()
  await expect(colegio.getByText('30 cuotas nuevas.', { exact: true })).toBeVisible()
  // Generar otra vez no duplica.
  await colegio.getByRole('button', { name: 'Generar cuotas' }).click()
  await expect(colegio.getByText('0 cuotas nuevas.', { exact: true })).toBeVisible()

  // Caja: abrir, buscar a Lucía, cobrar marzo con Yape y descargar el recibo.
  await colegio.goto('/panel/caja')
  await colegio.getByRole('button', { name: 'Abrir mi caja' }).click()
  await colegio.getByPlaceholder('Apellido, nombre o documento del alumno').fill('Quispe')
  await colegio.getByRole('button', { name: /QUISPE MAMANI, Lucía/ }).click()
  await colegio.getByRole('checkbox', { name: 'Cobrar Pensión Marzo' }).check()
  await colegio.getByLabel('Medio de pago').selectOption('yape')
  await colegio.getByLabel('N.° de operación').fill('op-123')
  await colegio.getByRole('button', { name: 'Cobrar S/ 350.00' }).click()
  await expect(colegio.getByText('Recibo R001-000001 · S/ 350.00')).toBeVisible()
  const descarga = colegio.waitForEvent('download')
  await colegio.getByRole('button', { name: 'Descargar recibo' }).click()
  expect((await descarga).suggestedFilename()).toBe('recibo-R001-000001.pdf')

  // El mismo número de operación con Yape no se acepta dos veces.
  await colegio.getByPlaceholder('Apellido, nombre o documento del alumno').fill('Quispe')
  await colegio.getByRole('button', { name: /QUISPE MAMANI, Lucía/ }).click()
  await colegio.getByRole('checkbox', { name: 'Cobrar Pensión Abril' }).check()
  await colegio.getByLabel('Medio de pago').selectOption('yape')
  await colegio.getByLabel('N.° de operación').fill('OP-123')
  await colegio.getByRole('button', { name: 'Cobrar S/ 350.00' }).click()
  await expect(colegio.getByText('Ese número de operación ya se registró para este medio de pago')).toBeVisible()

  // La familia (madre de Lucía, responsable de pago por ser la única) ve la cuota pagada y su recibo.
  const { familia: f } = semilla()
  const casa = await (await browser.newContext()).newPage()
  await casa.goto('/familia')
  await casa.getByLabel('DNI o carné de extranjería').fill(f.documento)
  await casa.getByLabel('PIN (6 números)').fill(f.pin)
  await casa.getByRole('button', { name: 'Ingresar', exact: true }).click()
  await casa.getByRole('navigation', { name: 'Secciones' }).getByRole('link', { name: 'Pagos' }).click()
  await expect(casa.getByRole('heading', { name: 'Pagos' })).toBeVisible()
  await expect(casa.getByText('R001-000001')).toBeVisible()
  await expect(casa.getByText('S/ 3,150.00')).toBeVisible()  // 9 cuotas por pagar
  const recibo = casa.waitForEvent('download')
  await casa.getByRole('button', { name: 'Descargar recibo R001-000001' }).click()
  expect((await recibo).suggestedFilename()).toBe('recibo-R001-000001.pdf')

  // Cerrar la caja con el efectivo contado (no hubo efectivo: cuadra con 0).
  await colegio.getByRole('button', { name: 'Cerrar caja' }).click()
  await colegio.getByLabel('Efectivo contado (S/)').fill('0')
  await expect(colegio.getByText('Cuadra con el efectivo cobrado.')).toBeVisible()
  await colegio.getByRole('button', { name: 'Cerrar caja' }).click()
  await expect(colegio.getByRole('button', { name: 'Abrir mi caja' })).toBeVisible()
  await colegio.goto('/panel/caja/cajas')
  await expect(colegio.getByText('Cuadra')).toBeVisible()
})
