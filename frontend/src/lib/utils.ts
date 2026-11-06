import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(value?: string | null, locale = 'en') {
  if (!value) return '—'
  try {
    const d = new Date(value)
    return d.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
      year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch { return String(value) }
}

export function timeAgo(value?: string | null, locale = 'en') {
  if (!value) return '—'
  const diff = Date.now() - new Date(value).getTime()
  const mins = Math.round(diff / 60000)
  const zh = locale === 'zh'
  if (mins < 1) return zh ? '刚刚' : 'just now'
  if (mins < 60) return zh ? `${mins} 分钟前` : `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`
  const days = Math.round(hours / 24)
  return zh ? `${days} 天前` : `${days}d ago`
}

export function truncate(text: string, max = 90) {
  const clean = (text || '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? clean.slice(0, max) + '…' : clean
}

export function safeParse<T = unknown>(text: string, fallback: T): T {
  try { return JSON.parse(text) as T } catch { return fallback }
}

export function b64urlToBuffer(value: string): ArrayBuffer {
  const pad = '='.repeat((4 - (value.length % 4)) % 4)
  const base64 = (value + pad).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const buf = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
  return buf.buffer
}

export function bufferToB64url(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf)
  let binary = ''
  bytes.forEach((b) => { binary += String.fromCharCode(b) })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function strToBuffer(value: string): ArrayBuffer {
  return new TextEncoder().encode(value).buffer as ArrayBuffer
}

export function downloadText(filename: string, text: string, type = 'application/json') {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); return true } catch { return false }
}

export function uid(prefix = 'id') {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`
}

export function initials(name?: string) {
  if (!name) return '?'
  const parts = name.replace(/[（(].*?[)）]/g, '').trim().split(/[\s/]+/)
  return (parts[0]?.[0] || '').toUpperCase() + (parts[1]?.[0] || '').toUpperCase()
}
