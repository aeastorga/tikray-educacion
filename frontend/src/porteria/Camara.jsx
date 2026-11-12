import { useEffect, useRef, useState } from 'react'
import { Mensaje } from '../espacios/comun/index.js'

const PAUSA_MISMO_CODIGO_MS = 4000 // el carnet sigue frente a la cámara: no es otra marcación

// Lee QR con la cámara trasera. Usa el lector del navegador (BarcodeDetector)
// cuando existe y, si no, jsQR, que se carga solo cuando hace falta.
export default function Camara({ alLeer }) {
  const video = useRef(null)
  const [error, setError] = useState(null)
  const leerRef = useRef(alLeer)
  leerRef.current = alLeer

  useEffect(() => {
    let flujo = null
    let activo = true
    let ultimo = { texto: '', cuando: 0 }
    const lienzo = document.createElement('canvas')

    async function iniciar() {
      try {
        flujo = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      } catch {
        setError('No se pudo abrir la cámara. Revisa el permiso del navegador o usa el lector.')
        return
      }
      if (!activo) return flujo.getTracks().forEach((t) => t.stop())
      video.current.srcObject = flujo
      await video.current.play().catch(() => {})

      let detectar
      if ('BarcodeDetector' in window) {
        const detector = new window.BarcodeDetector({ formats: ['qr_code'] })
        detectar = async () => (await detector.detect(video.current))[0]?.rawValue
      } else {
        const { default: jsQR } = await import('jsqr')
        detectar = async () => {
          const v = video.current
          if (!v.videoWidth) return null
          lienzo.width = v.videoWidth
          lienzo.height = v.videoHeight
          const ctx = lienzo.getContext('2d', { willReadFrequently: true })
          ctx.drawImage(v, 0, 0)
          return jsQR(ctx.getImageData(0, 0, lienzo.width, lienzo.height).data, lienzo.width, lienzo.height,
                      { inversionAttempts: 'dontInvert' })?.data
        }
      }

      while (activo) {
        const texto = await detectar().catch(() => null)
        const ahora = Date.now()
        if (texto && (texto !== ultimo.texto || ahora - ultimo.cuando > PAUSA_MISMO_CODIGO_MS)) {
          ultimo = { texto, cuando: ahora }
          leerRef.current(texto)
        } else if (texto) {
          ultimo.cuando = ahora
        }
        await new Promise((r) => setTimeout(r, 200))
      }
    }

    iniciar()
    return () => {
      activo = false
      flujo?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  if (error) return <Mensaje tipo="error">{error}</Mensaje>
  return <video ref={video} className="porteria-video" muted playsInline />
}
