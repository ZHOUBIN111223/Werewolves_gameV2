const PLAYER_PALETTE = ['#e68a5b', '#dec56b', '#5ba98a', '#688ed3', '#87a757', '#9b74e5', '#da6f8f', '#4db7bf', '#bd9155', '#74c17b', '#cb7d53', '#8aa4d5']

const SUBPHASE_LABELS = {
  setup: '布置',
  daybreak: '天亮',
  discussion: '讨论',
  voting: '投票',
  vote_resolution: '放逐结算',
  sheriff_campaign: '警长竞选',
  sheriff_voting: '警长投票',
  last_words: '遗言',
  last_words_complete: '遗言结束',
  guard: '守卫',
  witch: '女巫',
  seer: '预言家',
  resolve_night: '夜间结算',
  post_game: '终局',
}

const WINNER_LABELS = {
  villagers: '好人阵营',
  werewolves: '狼人阵营',
}

function trimText(text, maxLength = 72) {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength).trim()}…`
}

function clonePlayer(player, freshPlayers) {
  return {
    ...player,
    alive: freshPlayers ? true : player.alive,
    vote_target: freshPlayers ? null : player.vote_target,
    is_speaking: freshPlayers ? false : player.is_speaking,
  }
}

function getPlayerLookup(players) {
  return Object.fromEntries(players.map((player) => [player.id, player]))
}

function clearSpeaking(players) {
  for (const player of players) player.is_speaking = false
}

function clearVotes(players) {
  for (const player of players) player.vote_target = null
}

function firstValue(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== '') return value
  }

  return null
}

export function isPublicEvent(event) {
  return Array.isArray(event?.visibility) && event.visibility.includes('all')
}

export function shortPlayerName(id) {
  if (!id) return '??'
  return id.replace('player_', 'P')
}

export function formatPhaseLabel(phase) {
  if (!phase) return '未开始'
  if (phase === 'setup') return '开局'
  if (phase === 'post_game') return '终局'

  const dayMatch = phase.match(/^day_(\d+)$/)
  if (dayMatch) return `第 ${dayMatch[1]} 天`

  const nightMatch = phase.match(/^night_(\d+)$/)
  if (nightMatch) return `第 ${nightMatch[1]} 夜`

  return phase.replaceAll('_', ' ')
}

export function formatSubphaseLabel(subphase) {
  if (!subphase) return '等待中'
  return SUBPHASE_LABELS[subphase] ?? subphase.replaceAll('_', ' ')
}

export function formatWinnerLabel(winner) {
  if (!winner) return '胜负未定'
  return WINNER_LABELS[winner] ?? winner
}

export function getMoodFromPhase(phase) {
  if (phase?.startsWith('night')) {
    return {
      background: '#0b1120',
      fog: '#10192d',
      ambient: '#40607a',
      ambientIntensity: 1.15,
      moon: '#8ab1ff',
      moonIntensity: 1.9,
      fire: '#ffb258',
      fireIntensity: 22,
      ground: '#1e2a2a',
      ring: '#17211f',
      haze: '#15202b',
    }
  }

  if (phase === 'post_game') {
    return {
      background: '#2c1f17',
      fog: '#3d291d',
      ambient: '#7d6552',
      ambientIntensity: 1.2,
      moon: '#ffd07f',
      moonIntensity: 1.3,
      fire: '#ff9251',
      fireIntensity: 18,
      ground: '#463426',
      ring: '#301f17',
      haze: '#633f2b',
    }
  }

  return {
    background: '#1a2430',
    fog: '#223142',
    ambient: '#8a9aa8',
    ambientIntensity: 1.3,
    moon: '#d7e5ff',
    moonIntensity: 1.15,
    fire: '#ff9d4e',
    fireIntensity: 16,
    ground: '#354235',
    ring: '#243024',
    haze: '#2c4c44',
  }
}

export function getSeatPosition(seatNo, totalPlayers) {
  const safeTotal = Math.max(totalPlayers || 1, 1)
  const radius = safeTotal >= 10 ? 7.2 : safeTotal >= 8 ? 6.3 : 5.4
  const angle = ((seatNo - 1) / safeTotal) * Math.PI * 2 - Math.PI / 2

  return [Math.cos(angle) * radius, 0, Math.sin(angle) * radius]
}

export function getPlayerColor(player) {
  if (player?.accent) return player.accent
  const index = player?.seat_no ? (player.seat_no - 1) % PLAYER_PALETTE.length : 0
  return PLAYER_PALETTE[index]
}

export function getEventAnchorId(event) {
  const payload = event?.payload ?? {}

  return firstValue(
    payload.speaker,
    payload.voter,
    payload.eliminated_player,
    Array.isArray(payload.deaths) ? payload.deaths[0] : null,
    payload.badge_holder,
    payload.target,
    event?.actor,
  )
}

export function summarizeEvent(event) {
  const payload = event?.payload ?? {}

  switch (event?.system_name) {
    case 'phase_advanced':
      return `${formatPhaseLabel(payload.new_phase ?? event.phase)} · ${formatSubphaseLabel(payload.subphase)}`
    case 'speech_delivered':
      return `${shortPlayerName(payload.speaker)} 发言：${trimText(payload.content, 56)}`
    case 'vote_recorded':
    case 'sheriff_vote_recorded':
      return `${shortPlayerName(payload.voter)} 投给 ${shortPlayerName(payload.target)}`
    case 'player_eliminated':
      return `${shortPlayerName(payload.eliminated_player)} 出局`
    case 'night_deaths_announced':
      return payload.deaths?.length ? `昨夜倒下：${payload.deaths.map(shortPlayerName).join('、')}` : '昨夜平安'
    case 'speaking_order_announced':
      return `发言顺序：${(payload.speaking_order ?? []).map(shortPlayerName).join(' → ')}`
    case 'game_started':
      return '对局开始'
    case 'game_ended':
      return `${formatWinnerLabel(payload.winner)} 获胜`
    default:
      if (payload.message) return trimText(payload.message, 64)
      if (event?.system_name) return event.system_name.replaceAll('_', ' ')
      return event?.type ?? 'event'
  }
}

export function createSessionFromSnapshot(snapshot, options = {}) {
  const freshPlayers = options.freshPlayers ?? false
  const players = (snapshot?.players ?? []).map((player) => clonePlayer(player, freshPlayers))

  const session = {
    match: { ...snapshot.match },
    phase: snapshot?.match?.phase ?? 'setup',
    subphase: snapshot?.match?.current_subphase ?? 'setup',
    currentSpeaker: freshPlayers ? null : snapshot?.match?.current_speaker ?? null,
    focusTarget: freshPlayers ? null : snapshot?.match?.focus_target ?? null,
    winner: freshPlayers ? null : snapshot?.match?.winner ?? null,
    gameEnded: freshPlayers ? false : snapshot?.match?.game_ended ?? false,
    players,
    speakingOrder: [],
    speechLog: [],
    voteBursts: [],
    badgeHolder: null,
    lastEvent: null,
  }

  if (freshPlayers) {
    session.match.alive_players_count = players.length
    session.match.status = 'running'
    session.match.game_ended = false
    session.match.winner = null
    return session
  }

  const publicRecent = (snapshot?.recent_events ?? []).filter(isPublicEvent)
  return applyEventsSequentially(session, publicRecent)
}

export function applyEventsSequentially(session, events = []) {
  let nextSession = session
  for (const event of events) nextSession = applyEventToSession(nextSession, event)
  return nextSession
}

export function applyEventToSession(session, event) {
  if (!session || !event) return session

  const payload = event.payload ?? {}
  const players = session.players.map((player) => ({ ...player }))
  const playerById = getPlayerLookup(players)
  const next = {
    ...session,
    match: { ...session.match },
    players,
    speakingOrder: [...session.speakingOrder],
    speechLog: [...session.speechLog],
    voteBursts: [...session.voteBursts],
    lastEvent: event,
  }

  switch (event.system_name) {
    case 'phase_advanced':
      next.phase = payload.new_phase ?? event.phase ?? next.phase
      next.subphase = payload.subphase ?? next.subphase
      next.currentSpeaker = null
      clearSpeaking(players)
      if (payload.new_phase && payload.new_phase !== session.phase) clearVotes(players)
      break
    case 'speaking_order_announced':
      next.speakingOrder = [...(payload.speaking_order ?? [])]
      next.badgeHolder = payload.badge_holder ?? next.badgeHolder
      break
    case 'speech_delivered': {
      const speakerId = firstValue(payload.speaker, event.actor)
      clearSpeaking(players)
      if (speakerId && playerById[speakerId]) playerById[speakerId].is_speaking = true
      next.currentSpeaker = speakerId
      next.focusTarget = speakerId
      next.speechLog.unshift({ seq: event.seq, speaker: speakerId, content: payload.content ?? '' })
      break
    }
    case 'vote_recorded':
    case 'sheriff_vote_recorded': {
      const voterId = firstValue(payload.voter, event.actor)
      const targetId = payload.target ?? null
      if (voterId && playerById[voterId]) playerById[voterId].vote_target = targetId
      next.focusTarget = targetId
      next.voteBursts.push({ id: event.event_id, from: voterId, to: targetId, seq: event.seq })
      break
    }
    case 'player_eliminated': {
      const eliminatedId = payload.eliminated_player ?? payload.player ?? null
      if (eliminatedId && playerById[eliminatedId]) {
        playerById[eliminatedId].alive = false
        playerById[eliminatedId].is_speaking = false
        playerById[eliminatedId].vote_target = null
      }
      next.focusTarget = eliminatedId
      next.currentSpeaker = eliminatedId === next.currentSpeaker ? null : next.currentSpeaker
      break
    }
    case 'night_deaths_announced': {
      const deaths = Array.isArray(payload.deaths) ? payload.deaths : []
      for (const death of deaths) {
        if (playerById[death]) {
          playerById[death].alive = false
          playerById[death].is_speaking = false
          playerById[death].vote_target = null
        }
      }
      next.focusTarget = deaths[0] ?? null
      next.currentSpeaker = null
      break
    }
    case 'night_peaceful':
      next.focusTarget = null
      next.currentSpeaker = null
      break
    case 'sheriff_elected':
      next.badgeHolder = firstValue(payload.sheriff, payload.player, payload.elected_player)
      break
    case 'badge_transferred':
      next.badgeHolder = firstValue(payload.new_holder, payload.receiver, payload.to)
      break
    case 'badge_destroyed':
      next.badgeHolder = null
      break
    case 'last_words_announced':
      next.focusTarget = payload.speaker ?? next.focusTarget
      next.currentSpeaker = payload.speaker ?? next.currentSpeaker
      break
    case 'game_ended':
      next.phase = event.phase ?? 'post_game'
      next.subphase = 'post_game'
      next.winner = payload.winner ?? next.winner
      next.gameEnded = true
      next.currentSpeaker = null
      clearSpeaking(players)
      break
    default:
      break
  }

  next.match.phase = next.phase
  next.match.current_subphase = next.subphase
  next.match.current_speaker = next.currentSpeaker
  next.match.focus_target = next.focusTarget
  next.match.alive_players_count = players.filter((player) => player.alive).length
  next.match.game_ended = next.gameEnded
  next.match.winner = next.winner
  next.match.status = next.gameEnded ? 'finished' : next.match.status
  next.speechLog = next.speechLog.slice(0, 10)
  next.voteBursts = next.voteBursts.slice(-8)

  return next
}

export function mergeStatsWithEvents(stats, events = []) {
  if (!stats) return stats

  const next = {
    ...stats,
    total_events: stats.total_events,
    last_seq: stats.last_seq,
    counts_by_type: { ...stats.counts_by_type },
    counts_by_phase: { ...stats.counts_by_phase },
    counts_by_system_name: { ...stats.counts_by_system_name },
    counts_by_actor: { ...stats.counts_by_actor },
  }

  for (const event of events) {
    next.total_events += 1
    next.last_seq = Math.max(next.last_seq, event.seq)
    next.counts_by_type[event.type] = (next.counts_by_type[event.type] ?? 0) + 1
    next.counts_by_phase[event.phase] = (next.counts_by_phase[event.phase] ?? 0) + 1
    if (event.system_name) next.counts_by_system_name[event.system_name] = (next.counts_by_system_name[event.system_name] ?? 0) + 1
    if (event.actor) next.counts_by_actor[event.actor] = (next.counts_by_actor[event.actor] ?? 0) + 1
  }

  return next
}
