const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

function buildUrl(path, params = {}) {
  const base = API_BASE ? new URL(API_BASE) : new URL(window.location.origin)
  const url = new URL(path, base)

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    url.searchParams.set(key, String(value))
  }

  return url
}

async function requestJson(path, params = {}) {
  const response = await fetch(buildUrl(path, params), {
    headers: { accept: 'application/json' },
  })

  if (!response.ok) {
    let message = `HTTP ${response.status}`

    try {
      const payload = await response.json()
      message = payload.detail ?? message
    } catch {
      message = response.statusText || message
    }

    throw new Error(message)
  }

  return response.json()
}

export function fetchMatches() {
  return requestJson('/api/matches')
}

export function fetchMatchSnapshot(matchId, recentLimit = 24) {
  return requestJson(`/api/matches/${matchId}`, { recent_limit: recentLimit })
}

export function fetchMatchEvents(matchId, afterSeq = 0, limit = 100) {
  return requestJson(`/api/matches/${matchId}/events`, {
    after_seq: afterSeq,
    limit,
    visible_to: 'all',
  })
}

export function fetchMatchTimeline(matchId) {
  return requestJson(`/api/matches/${matchId}/timeline`, { visible_to: 'all' })
}

export function fetchMatchStats(matchId) {
  return requestJson(`/api/matches/${matchId}/stats`, { visible_to: 'all' })
}
