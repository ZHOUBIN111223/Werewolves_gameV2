const LOCAL_BUFFER_KEY = 'moonfire.runtime.buffer'
const SESSION_KEY = 'moonfire.runtime.session'
const FRONTEND_LOG_ENDPOINT = '/api/frontend-logs'
const MAX_LOCAL_ITEMS = 80

let handlersInstalled = false

function getSafeWindow() {
  return typeof window !== 'undefined' ? window : null
}

function getSafeNavigator() {
  return typeof navigator !== 'undefined' ? navigator : null
}

function createSessionId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

function getSessionId() {
  const browserWindow = getSafeWindow()
  if (!browserWindow?.sessionStorage) return createSessionId()

  const existing = browserWindow.sessionStorage.getItem(SESSION_KEY)
  if (existing) return existing

  const next = createSessionId()
  browserWindow.sessionStorage.setItem(SESSION_KEY, next)
  return next
}

function clipText(value, max = 2000) {
  const text = String(value ?? '')
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function serializeValue(value, depth = 0) {
  if (value == null) return value
  if (depth > 3) return '[max-depth]'

  if (value instanceof Error) {
    return {
      name: value.name,
      message: value.message,
      stack: clipText(value.stack ?? ''),
      cause: value.cause ? serializeValue(value.cause, depth + 1) : undefined,
    }
  }

  if (value instanceof Event) {
    return {
      type: value.type,
    }
  }

  if (Array.isArray(value)) {
    return value.slice(0, 12).map((item) => serializeValue(item, depth + 1))
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value).slice(0, 24)
    return Object.fromEntries(entries.map(([key, item]) => [key, serializeValue(item, depth + 1)]))
  }

  if (typeof value === 'string') return clipText(value, 1200)
  return value
}

function appendLocalBuffer(entry) {
  const browserWindow = getSafeWindow()
  if (!browserWindow?.localStorage) return

  try {
    const current = JSON.parse(browserWindow.localStorage.getItem(LOCAL_BUFFER_KEY) ?? '[]')
    const next = [...current, entry].slice(-MAX_LOCAL_ITEMS)
    browserWindow.localStorage.setItem(LOCAL_BUFFER_KEY, JSON.stringify(next))
  } catch {
    // Ignore storage failures. Runtime logging should never crash the UI.
  }
}

function sendToBackend(entry) {
  const browserWindow = getSafeWindow()
  if (!browserWindow?.fetch) return Promise.resolve()

  return browserWindow.fetch(FRONTEND_LOG_ENDPOINT, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(entry),
    keepalive: true,
  }).catch(() => {})
}

export function logRuntime(level, scope, message, context = {}) {
  const browserWindow = getSafeWindow()
  const browserNavigator = getSafeNavigator()
  const entry = {
    level,
    scope,
    message: clipText(message, 500),
    session_id: getSessionId(),
    href: browserWindow?.location?.href ?? null,
    user_agent: browserNavigator?.userAgent ?? null,
    client_time: new Date().toISOString(),
    context: serializeValue(context),
  }

  appendLocalBuffer(entry)
  void sendToBackend(entry)

  if (level === 'error') {
    console.error(`[runtime:${scope}] ${message}`, context)
    return
  }

  if (level === 'warn') {
    console.warn(`[runtime:${scope}] ${message}`, context)
    return
  }

  console.info(`[runtime:${scope}] ${message}`, context)
}

export function logInfo(scope, message, context = {}) {
  logRuntime('info', scope, message, context)
}

export function logWarn(scope, message, context = {}) {
  logRuntime('warn', scope, message, context)
}

export function logError(scope, message, context = {}) {
  logRuntime('error', scope, message, context)
}

export function installGlobalRuntimeHandlers() {
  const browserWindow = getSafeWindow()
  if (!browserWindow || handlersInstalled) return

  handlersInstalled = true

  browserWindow.addEventListener('error', (event) => {
    logError('window.error', event.message || 'Unhandled runtime error', {
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      error: event.error,
    })
  })

  browserWindow.addEventListener('unhandledrejection', (event) => {
    logError('window.unhandledrejection', 'Unhandled promise rejection', {
      reason: event.reason,
    })
  })

  browserWindow.addEventListener('vite:preloadError', (event) => {
    logError('window.preload', 'Vite preload failed', {
      payload: event.payload,
    })
  })

  logInfo('app.lifecycle', 'Frontend runtime handlers installed')
}

export function readLocalRuntimeBuffer() {
  const browserWindow = getSafeWindow()
  if (!browserWindow?.localStorage) return []

  try {
    return JSON.parse(browserWindow.localStorage.getItem(LOCAL_BUFFER_KEY) ?? '[]')
  } catch {
    return []
  }
}
