// Elegir archivo con el diseño del sistema y en castellano (el del navegador dice "Choose File / No file chosen"
// y en celular se sale del ancho). Va dentro de un <label> con su texto; `suelto` cuando no lo hay.
import { Paperclip } from 'lucide-react'
import { useState } from 'react'

export default function CampoArchivo({ onChange, multiple = false, suelto = false, texto, ...props }) {
  const [nombres, setNombres] = useState([])
  const Raiz = suelto ? 'label' : 'span'
  return (
    <Raiz className="archivo">
      <input type="file" className="archivo-input" multiple={multiple} {...props}
             onChange={(e) => { setNombres([...e.target.files].map((f) => f.name)); onChange?.(e) }} />
      <span className="boton secundario chico archivo-boton" aria-hidden="true">
        <Paperclip size={16} /> {texto || (multiple ? 'Elegir archivos' : 'Elegir archivo')}
      </span>
      <span className="archivo-nombre tenue" aria-live="polite">
        {nombres.length ? nombres.join(', ') : 'Ningún archivo elegido'}
      </span>
    </Raiz>
  )
}
