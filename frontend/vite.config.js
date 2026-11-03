import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// En local cada colegio entra por <subdominio>.localhost:5173 y el panel de
// Tikray Labs por plataforma.localhost:5173. El proxy conserva el Host para
// que el backend sepa de qué colegio es cada petición.
const backend = { target: process.env.BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: false }

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Tikray Educación',
        short_name: 'Colegio',
        lang: 'es-PE',
        display: 'standalone',
        start_url: '/',
        background_color: '#ffffff',
        theme_color: '#1F4E79',
        icons: [{ src: '/icono.svg', sizes: 'any', type: 'image/svg+xml' }],
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api/, /^\/plataforma/, /^\/archivos/],
        importScripts: ['/sw-push.js'],  // avisos push de la familia
        // Las fuentes quedan guardadas: la portería sin internet se sigue viendo igual.
        runtimeCaching: [{
          urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\//,
          handler: 'CacheFirst',
          options: { cacheName: 'fuentes', expiration: { maxEntries: 20, maxAgeSeconds: 31536000 },
            cacheableResponse: { statuses: [0, 200] } },
        }],
      },
    }),
  ],
  server: {
    host: true,
    allowedHosts: ['.localhost'],
    proxy: { '/api': backend, '/plataforma': backend, '/archivos': backend },
  },
})
