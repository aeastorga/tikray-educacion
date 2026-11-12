// Avisos push de la familia. Lo carga el service worker de la PWA (importScripts).

self.addEventListener('push', (evento) => {
  let m = {}
  try { m = evento.data ? evento.data.json() : {} } catch { m = { cuerpo: evento.data?.text() } }
  evento.waitUntil((async () => {
    // Ícono: el logo del colegio (o el de la app, en PNG: Android no muestra SVG). Insignia: la silueta blanca
    // de la barra de estado. La misma etiqueta reemplaza en vez de repetir.
    await self.registration.showNotification(m.titulo || 'Aviso del colegio', {
      body: m.cuerpo || '', tag: m.etiqueta, lang: 'es-PE', icon: m.icono || '/icono-192.png',
      badge: m.insignia || '/insignia-96.png', timestamp: m.momento || Date.now(), data: { url: m.url || '/familia' },
    })
    // Si la app está abierta, que refresque la tarjeta en vivo.
    for (const c of await self.clients.matchAll({ type: 'window' })) c.postMessage({ tipo: 'aviso' })
  })())
})

self.addEventListener('notificationclick', (evento) => {
  evento.notification.close()
  const url = evento.notification.data?.url || '/familia'
  evento.waitUntil((async () => {
    for (const c of await self.clients.matchAll({ type: 'window', includeUncontrolled: true })) {
      if (new URL(c.url).pathname.startsWith('/familia') && 'focus' in c) {
        // La app ya está abierta: llevarla a lo que avisa (p. ej. una entrada del cuaderno).
        if (new URL(c.url).pathname !== url && 'navigate' in c) {
          try { return (await c.navigate(url))?.focus() } catch { /* sin control del service worker */ }
        }
        return c.focus()
      }
    }
    return self.clients.openWindow(url)
  })())
})
