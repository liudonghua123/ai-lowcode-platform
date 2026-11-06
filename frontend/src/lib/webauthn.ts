import { b64urlToBuffer, bufferToB64url, strToBuffer } from './utils'

/** Convert backend WebAuthn options (base64url strings) into browser PublicKeyCredential options. */
function toPublicKeyOptions(options: any): PublicKeyCredentialCreationOptions | PublicKeyCredentialRequestOptions {
  const copy: any = { ...options }
  if (typeof copy.challenge === 'string') copy.challenge = b64urlToBuffer(copy.challenge)
  if (copy.user?.id && typeof copy.user.id === 'string') copy.user = { ...copy.user, id: b64urlToBuffer(copy.user.id) }
  if (Array.isArray(copy.excludeCredentials)) {
    copy.excludeCredentials = copy.excludeCredentials.map((c: any) => ({ ...c, id: b64urlToBuffer(c.id) }))
  }
  if (Array.isArray(copy.allowCredentials)) {
    copy.allowCredentials = copy.allowCredentials.map((c: any) => ({ ...c, id: b64urlToBuffer(c.id) }))
  }
  return copy
}

function serializeCredential(cred: PublicKeyCredential | null): any {
  if (!cred) throw new Error('No credential returned by the authenticator')
  const response: any = cred.response
  const out: any = {
    id: cred.id,
    rawId: bufferToB64url(cred.rawId),
    type: cred.type,
    response: { clientDataJSON: bufferToB64url(response.clientDataJSON) },
  }
  if ('attestationObject' in response && response.attestationObject) {
    out.response.attestationObject = bufferToB64url(response.attestationObject)
  }
  if ('authenticatorData' in response && response.authenticatorData) {
    out.response.authenticatorData = bufferToB64url(response.authenticatorData)
  }
  if ('signature' in response && response.signature) out.response.signature = bufferToB64url(response.signature)
  if ('userHandle' in response && response.userHandle) out.response.userHandle = bufferToB64url(response.userHandle)
  if (typeof cred.getClientExtensionResults === 'function') out.clientExtensionResults = cred.getClientExtensionResults()
  return out
}

export function webauthnAvailable() {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials
}

export async function registerPasskey(options: any) {
  if (!webauthnAvailable()) throw new Error('WebAuthn is unavailable (requires HTTPS or localhost)')
  const cred = await navigator.credentials.create({ publicKey: toPublicKeyOptions(options) as PublicKeyCredentialCreationOptions })
  return serializeCredential(cred as PublicKeyCredential)
}

export async function authenticatePasskey(options: any) {
  if (!webauthnAvailable()) throw new Error('WebAuthn is unavailable (requires HTTPS or localhost)')
  const cred = await navigator.credentials.get({ publicKey: toPublicKeyOptions(options) as PublicKeyCredentialRequestOptions })
  return serializeCredential(cred as PublicKeyCredential)
}

/** The challenge sent from the server is a plain string; decode its bytes for the browser. */
export function challengeBuffer(challenge: string) { return strToBuffer(challenge) }
