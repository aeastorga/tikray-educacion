import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// En local cada colegio entra por <subdominio>.localhost:5173 y el panel de
// Aulio (Tikray Labs) por plataforma.localhost:5173. El proxy conserva el Host para
// que el backend sepa de qué colegio es cada petición.
const backend = { target: process.env.BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: false }

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Aulio',
        description: 'Aulio by Tikray Labs: asistencia, avisos a la familia y cuaderno de control del colegio.',
        short_name: 'Aulio',
        lang: 'es-PE',
        display: 'standalone',
        start_url: '/',
        background_color: '#ffffff',
        theme_color: '#3B32C8',
        // PNG: el iPhone y las notificaciones de Android no usan SVG. Maskable: con margen para el recorte del sistema.
        icons: [
          { src: '/icono-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icono-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icono-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          { src: '/icono.svg', sizes: 'any', type: 'image/svg+xml' },
        ],
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api/, /^\/plataforma/, /^\/archivos/],
        importScripts: ['/sw-push.js'],  // avisos push de la familia
        // Las fuentes van en el precache: la portería se ve igual sin internet desde el primer uso.
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
      },
    }),
  ],
  server: {
    host: true,
    allowedHosts: ['.localhost'],
    proxy: { '/api': backend, '/plataforma': backend, '/archivos': backend },
  },
})
