// Envío de formularios en todo el sistema: mientras se envía, el botón muestra que está procesando y un
// segundo envío (doble clic, Enter otra vez) se ignora. Termina cuando acaban las peticiones que inició ese
// envío; si no inició ninguna (p. ej. pide confirmar primero), se libera enseguida.
import { peticionesEnCurso, seguirPeticiones } from './api.js'

export function instalarEnvio() {
  document.addEventListener('submit', (e) => {
    const forma = e.target
    if (!(forma instanceof HTMLFormElement)) return
    if (forma.dataset.enviando) { e.preventDefault(); e.stopPropagation(); return }
    const boton = e.submitter || forma.querySelector('button:not([type="button"]), input[type="submit"]')
    forma.dataset.enviando = '1'
    boton?.setAttribute('aria-busy', 'true')
    const antes = peticionesEnCurso()
    let vio = false
    const liberar = () => {
      quitar(); clearTimeout(espera)
      delete forma.dataset.enviando
      boton?.removeAttribute('aria-busy')
    }
    const hayPropias = () => [...peticionesEnCurso()].some((p) => !antes.has(p))
    const quitar = seguirPeticiones(() => {
      if (hayPropias()) vio = true
      else if (vio) liberar()
    })
    const espera = setTimeout(() => { if (!vio) liberar() }, 400)
  }, true)
}
