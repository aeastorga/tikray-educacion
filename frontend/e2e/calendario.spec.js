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

test('el colegio publica eventos (a una sección, con aviso), anula uno y la familia ve los de su hijo', async ({ browser }) => {
  const page = await browser.newPage()
  await ingresar(page, '/panel/calendario')
  await expect(page.getByRole('heading', { name: 'Calendario escolar' })).toBeVisible()

  // Un evento para la sección 1° A, con aviso a las familias.
  await page.getByRole('button', { name: 'Nuevo evento' }).click()
  const form = page.locator('form.form-evento')
  await form.getByLabel('Título').fill('Reunión de padres del bimestre')
  await form.getByLabel('Tipo').selectOption({ label: 'Reunión de padres' })
  await form.getByLabel('Fecha', { exact: true }).fill(enDias(3))
  await form.getByLabel('Hora (opcional)').fill('18:00')
  await form.getByLabel('Una o varias secciones').check()
  await form.getByLabel('1° A').check()
  await form.getByLabel(/Avisar a las familias/).check()
  await form.getByRole('button', { name: 'Publicar evento' }).click()
  await expect(page.getByRole('status')).toContainText('Evento publicado. Se avisó a 1 familia.')

  // Otro para todo el colegio, que luego se anula.
  await page.getByRole('button', { name: 'Nuevo evento' }).click()
  await form.getByLabel('Título').fill('Feria de ciencias')
  await form.getByLabel('Fecha', { exact: true }).fill(enDias(5))
  await form.getByRole('button', { name: 'Publicar evento' }).click()
  await expect(page.getByRole('status')).toContainText('Evento publicado.')

  await page.getByRole('link', { name: 'Próximos' }).click()
  const feria = page.locator('.tarjeta-evento', { hasText: 'Feria de ciencias' })
  await expect(page.locator('.tarjeta-evento', { hasText: 'Reunión de padres del bimestre' })).toContainText('Primaria · 1° A')
  await feria.getByRole('button', { name: 'Anular' }).click()
  await feria.getByLabel('Motivo de la anulación').fill('Obras en el patio')
  await feria.getByRole('button', { name: 'Anular evento' }).click()
  await expect(page.getByRole('status')).toContainText('Evento anulado')
  await expect(page.locator('.tarjeta-evento', { hasText: 'Feria de ciencias' })).toHaveCount(0)

  // En el mes sigue visible como anulado; el PDF del mes se descarga.
  await page.getByRole('link', { name: 'Mes', exact: true }).click()
  const dia5 = enDias(5)
  const mesActual = enDias(0).slice(0, 7)
  if (dia5.slice(0, 7) !== mesActual) await page.getByRole('button', { name: 'Mes siguiente' }).click()
  await page.getByRole('gridcell', { name: new RegExp(`^${Number(dia5.slice(8))} de `) }).click()
  const detalle = page.locator('.detalle-dia')
  await expect(detalle).toContainText('Feria de ciencias')
  await expect(detalle).toContainText('Anulado')
  await expect(detalle).toContainText('Motivo: Obras en el patio')
  const descarga = page.waitForEvent('download')
  await page.getByRole('button', { name: 'PDF del mes' }).click()
  expect((await descarga).suggestedFilename()).toMatch(/^calendario-\d{4}-\d{2}\.pdf$/)

  // Inicio: tarjeta de próximos eventos.
  await page.goto('/panel')
  await expect(page.getByRole('heading', { name: 'Próximos eventos' })).toBeVisible()
  await expect(page.locator('.proximos-inicio')).toContainText('Reunión de padres del bimestre')
  await page.close()

  // La familia: pestaña Calendario con el evento de la sección de su hija.
  const casa = await browser.newPage()
  await familia(casa)
  await casa.getByRole('link', { name: 'Calendario' }).click()
  await expect(casa.getByRole('heading', { name: 'Calendario' })).toBeVisible()
  const reunion = casa.locator('.tarjeta-evento', { hasText: 'Reunión de padres del bimestre' })
  await expect(reunion).toContainText('Para Lucía')
  await expect(reunion).toContainText('18:00')
  await expect(casa.locator('.tarjeta-evento', { hasText: 'Feria de ciencias' })).toHaveCount(0)
  await casa.getByRole('button', { name: 'Mes', exact: true }).click()
  await expect(casa.locator('.mes-calendario')).toBeVisible()
  await casa.close()
})
