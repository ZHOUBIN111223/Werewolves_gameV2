import { startTransition, useEffect, useEffectEvent, useRef, useState } from 'react'
import { getDemoEvents, getDemoMatches, getDemoSnapshot, getDemoStats, getDemoTimeline, isDemoMatchId } from '../data/demoMatch'
import { applyEventsSequentially, createSessionFromSnapshot, isPublicEvent, mergeStatsWithEvents } from '../lib/gameState'
import { fetchMatchEvents, fetchMatches, fetchMatchSnapshot, fetchMatchStats, fetchMatchTimeline } from '../lib/observerApi'
import { logError, logInfo, logWarn } from '../lib/runtimeLogger'

function getErrorMessage(error) {
  if (error instanceof Error) return error.message
  return String(error ?? 'unknown error')
}

function pickSelectedMatchId(items, currentMatchId, preferredMatchId) {
  if (!items.length) return null

  if (preferredMatchId && items.some((item) => item.match_id === preferredMatchId)) {
    return preferredMatchId
  }

  const latestMatchId = items[0].match_id
  if (!currentMatchId) return latestMatchId

  const currentItem = items.find((item) => item.match_id === currentMatchId)
  if (!currentItem) return latestMatchId

  const newestRunningItem = items.find((item) => item.status !== 'finished')
  if (currentItem.status === 'finished' && newestRunningItem && newestRunningItem.match_id !== currentMatchId) {
    return newestRunningItem.match_id
  }

  return currentMatchId
}

export function useWerewolfObserver() {
  const [source, setSource] = useState('connecting')
  const [matches, setMatches] = useState([])
  const [selectedMatchId, setSelectedMatchId] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [liveSession, setLiveSession] = useState(null)
  const [stats, setStats] = useState(null)
  const [eventFeed, setEventFeed] = useState([])
  const [timelineState, setTimelineState] = useState({ matchId: null, items: [], loading: false })
  const [loading, setLoading] = useState({ matches: true, match: false })
  const [connection, setConnection] = useState({ state: 'connecting', label: '连接对局后端' })

  const afterSeqRef = useRef(0)
  const connectionSignatureRef = useRef('')

  useEffect(() => {
    logInfo('observer.lifecycle', 'Observer hook mounted')
  }, [])

  async function refreshMatches(preferredMatchId, options = {}) {
    const background = options.background ?? false
    const allowDemoFallback = options.allowDemoFallback ?? !background

    if (!background) {
      setLoading((current) => ({ ...current, matches: true }))
    }

    try {
      const payload = await fetchMatches()
      const items = payload.items ?? []
      if (!items.length) throw new Error('no matches found')

      startTransition(() => {
        setSource('live')
        setMatches(items)
        setSelectedMatchId((current) => {
          return pickSelectedMatchId(items, current, preferredMatchId)
        })
      })

      setConnection({ state: 'online', label: '后端在线' })
      logInfo('observer.matches', 'Loaded live matches', {
        count: items.length,
        preferredMatchId,
        background,
      })
    } catch (error) {
      if (!allowDemoFallback && source === 'live' && matches.length > 0) {
        setConnection({ state: 'offline', label: getErrorMessage(error) || '大厅刷新失败' })
        logWarn('observer.matches', 'Failed to refresh live matches, keeping current live state', {
          preferredMatchId,
          background,
          error,
        })
        return
      }

      const payload = getDemoMatches()

      startTransition(() => {
        setSource('demo')
        setMatches(payload.items)
        setSelectedMatchId(payload.items[0]?.match_id ?? null)
      })

      setConnection({ state: 'demo', label: '演示局已接管' })
      logWarn('observer.matches', 'Live match list unavailable, switched to demo mode', {
        preferredMatchId,
        count: payload.items.length,
        error,
        background,
      })
    } finally {
      if (!background) {
        setLoading((current) => ({ ...current, matches: false }))
      }
    }
  }

  const refreshMatchesEvent = useEffectEvent((preferredMatchId, options = {}) => {
    void refreshMatches(preferredMatchId, options)
  })

  useEffect(() => {
    refreshMatchesEvent()
  }, [])

  useEffect(() => {
    if (source !== 'live') return undefined

    const timer = window.setInterval(() => {
      refreshMatchesEvent(undefined, { background: true, allowDemoFallback: false })
    }, 5000)

    return () => {
      window.clearInterval(timer)
    }
  }, [source])

  useEffect(() => {
    if (!selectedMatchId) return undefined

    let cancelled = false
    setLoading((current) => ({ ...current, match: true }))

    startTransition(() => {
      setTimelineState({ matchId: null, items: [], loading: false })
    })

    async function loadMatch() {
      try {
        const demoMode = source === 'demo' || isDemoMatchId(selectedMatchId)
        const [snapshotPayload, statsPayload] = demoMode
          ? [getDemoSnapshot(selectedMatchId), getDemoStats(selectedMatchId)]
          : await Promise.all([fetchMatchSnapshot(selectedMatchId), fetchMatchStats(selectedMatchId)])

        if (cancelled) return

        afterSeqRef.current = snapshotPayload.recent_events.at(-1)?.seq ?? snapshotPayload.match.last_seq ?? 0

        startTransition(() => {
          setSnapshot(snapshotPayload)
          setLiveSession(createSessionFromSnapshot(snapshotPayload))
          setStats(statsPayload)
          setEventFeed(snapshotPayload.recent_events.filter(isPublicEvent).slice().reverse())
        })

        setConnection({ state: demoMode ? 'demo' : 'online', label: demoMode ? '演示局运行中' : '后端在线' })
        logInfo('observer.match', 'Loaded match snapshot', {
          matchId: selectedMatchId,
          source: demoMode ? 'demo' : 'live',
          players: snapshotPayload.players?.length ?? 0,
          recentEvents: snapshotPayload.recent_events?.length ?? 0,
        })
      } catch (error) {
        if (cancelled) return

        startTransition(() => {
          setSnapshot(null)
          setLiveSession(null)
          setStats(null)
          setEventFeed([])
        })

        setConnection({ state: 'offline', label: getErrorMessage(error) || '读取对局失败' })
        logError('observer.match', 'Failed to load match snapshot', {
          matchId: selectedMatchId,
          source,
          error,
        })
      } finally {
        if (!cancelled) setLoading((current) => ({ ...current, match: false }))
      }
    }

    loadMatch()

    return () => {
      cancelled = true
    }
  }, [selectedMatchId, source])

  const pollLatestEvents = useEffectEvent(async () => {
    if (!selectedMatchId || !snapshot) return

    const demoMode = source === 'demo' || isDemoMatchId(selectedMatchId)

    try {
      const payload = demoMode ? getDemoEvents(selectedMatchId, afterSeqRef.current, 2) : await fetchMatchEvents(selectedMatchId, afterSeqRef.current, 4)
      if (!payload.events.length) return

      afterSeqRef.current = payload.next_seq

      startTransition(() => {
        setLiveSession((current) => applyEventsSequentially(current, payload.events))
        setStats((current) => mergeStatsWithEvents(current, payload.events))
        setEventFeed((current) => [...payload.events.slice().reverse(), ...current].slice(0, 18))
      })

      setConnection({ state: demoMode ? 'demo' : 'online', label: demoMode ? '演示局运行中' : '实时轮询中' })
    } catch (error) {
      if (!demoMode) {
        setConnection({ state: 'offline', label: getErrorMessage(error) || '轮询中断' })
        logWarn('observer.poll', 'Failed to poll latest events', {
          matchId: selectedMatchId,
          afterSeq: afterSeqRef.current,
          error,
        })
      }
    }
  })

  useEffect(() => {
    if (!selectedMatchId || !snapshot) return undefined

    const pollMs = source === 'demo' ? 1900 : 1300
    const timer = window.setInterval(() => {
      pollLatestEvents()
    }, pollMs)

    return () => {
      window.clearInterval(timer)
    }
  }, [selectedMatchId, snapshot, source])

  async function ensureTimeline() {
    if (!selectedMatchId) return []
    if (timelineState.matchId === selectedMatchId && timelineState.items.length > 0) return timelineState.items

    setTimelineState((current) => ({
      matchId: selectedMatchId,
      items: current.matchId === selectedMatchId ? current.items : [],
      loading: true,
    }))

    try {
      const demoMode = source === 'demo' || isDemoMatchId(selectedMatchId)
      const items = demoMode ? getDemoTimeline(selectedMatchId) : await fetchMatchTimeline(selectedMatchId)

      startTransition(() => {
        setTimelineState({ matchId: selectedMatchId, items, loading: false })
      })

      logInfo('observer.timeline', 'Loaded timeline', {
        matchId: selectedMatchId,
        items: items.length,
      })
      return items
    } catch (error) {
      setTimelineState({ matchId: selectedMatchId, items: [], loading: false })
      logWarn('observer.timeline', 'Failed to load timeline', {
        matchId: selectedMatchId,
        error,
      })
      return []
    }
  }

  useEffect(() => {
    const signature = [source, selectedMatchId ?? 'none', connection.state, connection.label].join(':')
    if (connectionSignatureRef.current === signature) return

    connectionSignatureRef.current = signature

    const payload = {
      source,
      selectedMatchId,
      state: connection.state,
      label: connection.label,
      matches: matches.length,
    }

    if (connection.state === 'offline') {
      logWarn('observer.connection', 'Observer connection degraded', payload)
      return
    }

    logInfo('observer.connection', 'Observer connection updated', payload)
  }, [source, selectedMatchId, connection.state, connection.label, matches.length])

  return {
    source,
    matches,
    selectedMatchId,
    setSelectedMatchId,
    snapshot,
    liveSession,
    stats,
    eventFeed,
    timeline: timelineState.items,
    timelineLoading: timelineState.loading,
    loading,
    connection,
    ensureTimeline,
    refreshMatches,
  }
}
