// Passkeys (huella o rostro del celular). El servidor manda las opciones en JSON
// con base64url; el navegador las necesita en binario y viceversa.

export const hayPasskeys = () => typeof window.PublicKeyCredential === 'function'

function aBytes(b64url) {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((b64url.length + 3) % 4)
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
}

function aTexto(buffer) {
  let s = ''
  for (const b of new Uint8Array(buffer)) s += String.fromCharCode(b)
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

const credencialesBinarias = (lista = []) => lista.map((c) => ({ ...c, id: aBytes(c.id) }))

export async function crearPasskey(opciones) {
  const c = await navigator.credentials.create({ publicKey: {
    ...opciones,
    challenge: aBytes(opciones.challenge),
    user: { ...opciones.user, id: aBytes(opciones.user.id) },
    excludeCredentials: credencialesBinarias(opciones.excludeCredentials),
  } })
  return {
    id: c.id, rawId: aTexto(c.rawId), type: c.type,
    response: {
      clientDataJSON: aTexto(c.response.clientDataJSON),
      attestationObject: aTexto(c.response.attestationObject),
      transports: c.response.getTransports?.() || [],
    },
    clientExtensionResults: c.getClientExtensionResults?.() || {},
  }
}

export async function usarPasskey(opciones) {
  const c = await navigator.credentials.get({ publicKey: {
    ...opciones,
    challenge: aBytes(opciones.challenge),
    allowCredentials: credencialesBinarias(opciones.allowCredentials),
  } })
  return {
    id: c.id, rawId: aTexto(c.rawId), type: c.type,
    response: {
      clientDataJSON: aTexto(c.response.clientDataJSON),
      authenticatorData: aTexto(c.response.authenticatorData),
      signature: aTexto(c.response.signature),
      userHandle: c.response.userHandle ? aTexto(c.response.userHandle) : null,
    },
    clientExtensionResults: c.getClientExtensionResults?.() || {},
  }
}

// La llave pública VAPID viene en base64url; pushManager la quiere en bytes.
export const llaveVapid = aBytes
