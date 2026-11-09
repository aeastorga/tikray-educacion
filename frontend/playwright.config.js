import { defineConfig, devices } from '@playwright/test'

// Pruebas de navegador. Levantan su propio backend (puerto 8001) y Vite (5174)
// contra una base aparte, E2E_DATABASE_URL, que se borra y se siembra en cada corrida.
//   E2E_DATABASE_URL=postgresql+psycopg:///tikray_e2e npm run e2e
const BASE_DATOS = process.env.E2E_DATABASE_URL || 'postgresql+psycopg:///tikray_e2e'
const ENTORNO = {
  DATABASE_URL: BASE_DATOS,
  E2E_DATABASE_URL: BASE_DATOS,
  SECRET_KEY: 'clave-de-pruebas-e2e-' + 'x'.repeat(32),
  DOMINIO_BASE: 'localhost',
  TAREAS_EN_FONDO: 'false',
  CARPETA_ARCHIVOS: 'archivos-e2e',
  FACTURACION_CLAVE: 'clave-de-facturacion-e2e-' + 'x'.repeat(16),
}

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/preparar.js',
  workers: 1, // comparten la base y una prueba cierra las sesiones del administrador
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://e2e.localhost:5174',
    trace: 'retain-on-failure',
    ...devices['Pixel 7'], // la portería es un celular
  },
  webServer: [
    {
      command: '.venv/bin/uvicorn app.main:app --port 8001',
      cwd: '../backend',
      url: 'http://127.0.0.1:8001/salud',
      env: ENTORNO,
      reuseExistingServer: false,
    },
    {
      command: 'npx vite --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      env: { BACKEND_URL: 'http://127.0.0.1:8001' },
      reuseExistingServer: false,
    },
  ],
})
