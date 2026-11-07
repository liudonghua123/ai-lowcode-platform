export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const TOKEN_KEY = 'ailp_token'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

export function getToken() { return localStorage.getItem(TOKEN_KEY) || '' }
export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  auth?: boolean
  raw?: boolean
}

export async function api<T = any>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, raw = false, headers, ...rest } = options
  const h: Record<string, string> = { ...(headers as Record<string, string> || {}) }
  if (body !== undefined && !raw) h['Content-Type'] = 'application/json'
  const token = getToken()
  if (auth && token && !h['Authorization']) h['Authorization'] = `Bearer ${token}`
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: h,
      body: body === undefined ? undefined : raw ? (body as BodyInit) : JSON.stringify(body),
    })
  } catch (err) {
    throw new ApiError(0, `Network error: ${String(err)}`)
  }
  if (!response.ok) {
    let detail: any = null
    try { detail = await response.json() } catch { /* ignore */ }
    const message = typeof detail?.detail === 'string' ? detail.detail
      : Array.isArray(detail?.detail) ? JSON.stringify(detail.detail)
      : `HTTP ${response.status}`
    if (response.status === 401 && auth) window.dispatchEvent(new CustomEvent('ailp:unauthorized'))
    throw new ApiError(response.status, message, detail)
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  try { return JSON.parse(text) as T } catch { return text as unknown as T }
}

export const get = <T = any>(p: string, o?: RequestOptions) => api<T>(p, { ...o, method: 'GET' })
export const post = <T = any>(p: string, b?: unknown, o?: RequestOptions) =>
  api<T>(p, { ...o, method: 'POST', body: b })
export const put = <T = any>(p: string, b?: unknown, o?: RequestOptions) =>
  api<T>(p, { ...o, method: 'PUT', body: b })
export const del = <T = any>(p: string, o?: RequestOptions) => api<T>(p, { ...o, method: 'DELETE' })
/** multipart/form-data upload — pass a FormData as body, no Content-Type override. */
export const upload = <T = any>(p: string, form: FormData, o?: RequestOptions) =>
  api<T>(p, { ...o, method: 'POST', body: form, raw: true })
