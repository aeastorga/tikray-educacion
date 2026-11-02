import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// En local cada colegio entra por <subdominio>.localhost:5173 y el panel de
// Tikray Labs por plataforma.localhost:5173. El proxy conserva el Host para
// que el backend sepa de qué colegio es cada petición.
const backend = { target: 'http://127.0.0.1:8000', changeOrigin: false }

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
      workbox: { navigateFallbackDenylist: [/^\/api/, /^\/plataforma/, /^\/archivos/] },
    }),
  ],
  server: {
    host: true,
    allowedHosts: ['.localhost'],
    proxy: { '/api': backend, '/plataforma': backend, '/archivos': backend },
  },
})
