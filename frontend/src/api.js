// Small fetch wrapper: adds the login token, turns error responses into exceptions.

const TOKEN_KEY = 'seatlock.token'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* private mode: stay logged in for this tab only */ }
}

export class ApiError extends Error {
  constructor(status, body) {
    super(typeof body?.detail === 'string' ? body.detail : 'Something went wrong')
    this.status = status
    this.code = body?.code
    this.body = body
  }
}

export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const token = getToken()
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return null
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    // FastAPI validation errors come back as a list
    if (Array.isArray(data?.detail)) data.detail = data.detail.map((d) => d.msg).join(', ')
    throw new ApiError(res.status, data)
  }
  return data
}

export const rupees = (paise) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(paise / 100)

export const showTime = (iso) =>
  new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

export function seatSocket(showId, onMessage) {
  // Reconnects on its own if the connection drops. Returns a function that closes it.
  let ws, closed = false, retry
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/ws/shows/${showId}`)
    ws.onmessage = (e) => onMessage(JSON.parse(e.data))
    ws.onclose = () => { if (!closed) retry = setTimeout(open, 1500) }
  }
  open()
  return () => { closed = true; clearTimeout(retry); ws?.close() }
}
