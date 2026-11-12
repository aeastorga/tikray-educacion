import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Íconos PNG de la app (iPhone y notificaciones de Android no usan SVG): existen, tienen su tamaño, el manifest
// los lista y la insignia es de un solo color (blanco sobre transparente).
const ICONOS = [['/icono-192.png', 192], ['/icono-512.png', 512], ['/icono-maskable-512.png', 512],
  ['/apple-touch-icon.png', 180], ['/insignia-96.png', 96]]
const leer = (ruta) => readFileSync(new URL(ruta, import.meta.url), 'utf8')

test('los íconos PNG existen, tienen su tamaño y el manifest y el index los listan', async ({ page }) => {
  await page.goto('/')
  for (const [ruta, px] of ICONOS) {
    const medida = await page.evaluate(async (src) => {
      const r = await fetch(src)
      if (!r.ok || r.headers.get('content-type') !== 'image/png') return null
      const img = await createImageBitmap(await r.blob())
      return [img.width, img.height]
    }, ruta)
    expect(medida, ruta).toEqual([px, px])
  }
  const config = leer('../vite.config.js')
  for (const [src, tam, extra] of [['/icono-192.png', '192x192', ''], ['/icono-512.png', '512x512', ''],
    ['/icono-maskable-512.png', '512x512', "purpose: 'maskable'"]]) {
    const linea = config.split('\n').find((l) => l.includes(`src: '${src}'`))
    expect(linea, `manifest: ${src}`).toContain(`sizes: '${tam}'`)
    expect(linea).toContain("type: 'image/png'")
    if (extra) expect(linea).toContain(extra)
  }
  const index = leer('../index.html')
  expect(index).toContain('<link rel="apple-touch-icon" href="/apple-touch-icon.png" />')
  expect(index).toContain('name="apple-mobile-web-app-capable"')
  expect(index).toContain('name="apple-mobile-web-app-title"')
  expect(index).toContain('name="apple-mobile-web-app-status-bar-style"')
  // El service worker usa la insignia y el ícono PNG (no el SVG).
  const sw = leer('../public/sw-push.js')
  expect(sw).toContain("badge: m.insignia || '/insignia-96.png'")
  expect(sw).not.toContain('icono.svg')
})

test('la insignia es blanca sobre transparente', async ({ page }) => {
  await page.goto('/')
  const colores = await page.evaluate(async () => {
    const img = await createImageBitmap(await (await fetch('/insignia-96.png')).blob())
    const lienzo = new OffscreenCanvas(img.width, img.height)
    const ctx = lienzo.getContext('2d')
    ctx.drawImage(img, 0, 0)
    const d = ctx.getImageData(0, 0, img.width, img.height).data
    let opacos = 0, transparentes = 0, otros = 0
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) transparentes++
      else if (d[i + 3] < 128) continue  // borde suavizado: el color se redondea al guardarse premultiplicado
      else if (d[i] > 240 && d[i + 1] > 240 && d[i + 2] > 240) opacos++
      else otros++
    }
    return { opacos, transparentes, otros }
  })
  expect(colores.otros).toBe(0)
  expect(colores.opacos).toBeGreaterThan(500)
  expect(colores.transparentes).toBeGreaterThan(colores.opacos)
})
