const API_BASE = '/minutestrace/api'

export const session = {
  get token() { return localStorage.getItem('mt_token') || '' },
  set token(value: string) { value ? localStorage.setItem('mt_token', value) : localStorage.removeItem('mt_token') },
  get user() { try { return JSON.parse(localStorage.getItem('mt_user') || 'null') } catch { return null } },
  set user(value: any) { value ? localStorage.setItem('mt_user', JSON.stringify(value)) : localStorage.removeItem('mt_user') },
  clear() { localStorage.removeItem('mt_token'); localStorage.removeItem('mt_user') },
}

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (session.token) headers.set('Authorization', `Bearer ${session.token}`)
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (response.status === 401) {
    session.clear()
    if (!location.pathname.endsWith('/login')) location.href = '/minutestrace/login'
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(payload.detail || `请求失败（${response.status}）`)
  }
  return response.json()
}

export async function downloadExport(meetingId: number, format: 'docx' | 'pdf') {
  const response = await fetch(`${API_BASE}/meetings/${meetingId}/export?format=${format}`, { headers: { Authorization: `Bearer ${session.token}` } })
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || '导出失败')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `会议纪要.${format}`
  anchor.click()
  URL.revokeObjectURL(url)
}
