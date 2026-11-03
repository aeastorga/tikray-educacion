import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Base nueva para cada corrida; los datos que necesitan las pruebas quedan en e2e/.semilla.json.
export default function preparar() {
  const backend = fileURLToPath(new URL('../../backend', import.meta.url))
  const salida = execFileSync('.venv/bin/python', ['-m', 'tests.e2e_semilla'], {
    cwd: backend,
    env: { ...process.env, E2E_DATABASE_URL: process.env.E2E_DATABASE_URL || 'postgresql+psycopg:///tikray_e2e' },
  })
  writeFileSync(new URL('./.semilla.json', import.meta.url), salida)
}
