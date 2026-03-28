const DEMO_MATCH_ID = 'demo_moonfire_court'

const demoPlayers = [
  { id: 'player_0', seat_no: 1, name: 'player_0', alive: true, role: null, camp: null, suspicion: 0.64, vote_target: null, is_speaking: false, accent: '#b65d3a' },
  { id: 'player_1', seat_no: 2, name: 'player_1', alive: true, role: null, camp: null, suspicion: 0.24, vote_target: null, is_speaking: false, accent: '#d4b764' },
  { id: 'player_2', seat_no: 3, name: 'player_2', alive: true, role: null, camp: null, suspicion: 0.38, vote_target: null, is_speaking: false, accent: '#4b8a7d' },
  { id: 'player_3', seat_no: 4, name: 'player_3', alive: true, role: null, camp: null, suspicion: 0.31, vote_target: null, is_speaking: false, accent: '#7d90c1' },
  { id: 'player_4', seat_no: 5, name: 'player_4', alive: true, role: null, camp: null, suspicion: 0.49, vote_target: null, is_speaking: false, accent: '#80a15a' },
  { id: 'player_5', seat_no: 6, name: 'player_5', alive: true, role: null, camp: null, suspicion: 0.35, vote_target: null, is_speaking: false, accent: '#8d66c8' },
]

const demoTimeline = [
  { event_id: 'demo-100', match_id: DEMO_MATCH_ID, seq: 100, type: 'system', phase: 'setup', visibility: ['all'], ts: 100, payload: { message: 'game_started', players: demoPlayers.map((player) => player.id) }, actor: null, action_type: null, system_name: 'game_started' },
  { event_id: 'demo-200', match_id: DEMO_MATCH_ID, seq: 200, type: 'system', phase: 'day_1', visibility: ['all'], ts: 200, payload: { message: 'Phase advanced to day_1', new_phase: 'day_1', previous_phase: 'setup', subphase: 'discussion' }, actor: null, action_type: null, system_name: 'phase_advanced' },
  { event_id: 'demo-300', match_id: DEMO_MATCH_ID, seq: 300, type: 'system', phase: 'day_1', visibility: ['all'], ts: 300, payload: { badge_holder: null, speaking_order: demoPlayers.map((player) => player.id) }, actor: null, action_type: null, system_name: 'speaking_order_announced' },
  { event_id: 'demo-400', match_id: DEMO_MATCH_ID, seq: 400, type: 'system', phase: 'day_1', visibility: ['all'], ts: 400, payload: { speaker: 'player_1', content: '我是预言家，首夜查到 player_0 是狼人。今天先把查杀推出去，别让狼有机会带节奏。' }, actor: null, action_type: null, system_name: 'speech_delivered' },
  { event_id: 'demo-500', match_id: DEMO_MATCH_ID, seq: 500, type: 'system', phase: 'day_1', visibility: ['all'], ts: 500, payload: { speaker: 'player_0', content: '这个查杀我不认。我更怀疑 player_1 借预言家身份抢警徽，大家不要只听单边叙事。' }, actor: null, action_type: null, system_name: 'speech_delivered' },
  { event_id: 'demo-600', match_id: DEMO_MATCH_ID, seq: 600, type: 'system', phase: 'day_1', visibility: ['all'], ts: 600, payload: { message: 'player_2 voted for player_0', voter: 'player_2', target: 'player_0' }, actor: null, action_type: null, system_name: 'vote_recorded' },
  { event_id: 'demo-700', match_id: DEMO_MATCH_ID, seq: 700, type: 'system', phase: 'day_1', visibility: ['all'], ts: 700, payload: { message: 'player_4 voted for player_0', voter: 'player_4', target: 'player_0' }, actor: null, action_type: null, system_name: 'vote_recorded' },
  { event_id: 'demo-800', match_id: DEMO_MATCH_ID, seq: 800, type: 'system', phase: 'day_1', visibility: ['all'], ts: 800, payload: { message: 'player_5 voted for player_0', voter: 'player_5', target: 'player_0' }, actor: null, action_type: null, system_name: 'vote_recorded' },
  { event_id: 'demo-900', match_id: DEMO_MATCH_ID, seq: 900, type: 'system', phase: 'day_1', visibility: ['all'], ts: 900, payload: { eliminated_player: 'player_0', reason: 'eliminated by vote' }, actor: null, action_type: null, system_name: 'player_eliminated' },
  { event_id: 'demo-1000', match_id: DEMO_MATCH_ID, seq: 1000, type: 'system', phase: 'night_1', visibility: ['all'], ts: 1000, payload: { message: 'Phase advanced to night_1', new_phase: 'night_1', previous_phase: 'day_1', subphase: 'seer' }, actor: null, action_type: null, system_name: 'phase_advanced' },
  { event_id: 'demo-1100', match_id: DEMO_MATCH_ID, seq: 1100, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1100, payload: { message: 'Phase advanced to day_2', new_phase: 'day_2', previous_phase: 'night_1', subphase: 'daybreak' }, actor: null, action_type: null, system_name: 'phase_advanced' },
  { event_id: 'demo-1200', match_id: DEMO_MATCH_ID, seq: 1200, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1200, payload: { message: '昨夜 player_3 倒下了', deaths: ['player_3'] }, actor: null, action_type: null, system_name: 'night_deaths_announced' },
  { event_id: 'demo-1300', match_id: DEMO_MATCH_ID, seq: 1300, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1300, payload: { message: 'Phase advanced to day_2 discussion', new_phase: 'day_2', previous_phase: 'day_2', subphase: 'discussion' }, actor: null, action_type: null, system_name: 'phase_advanced' },
  { event_id: 'demo-1400', match_id: DEMO_MATCH_ID, seq: 1400, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1400, payload: { badge_holder: null, speaking_order: ['player_2', 'player_4', 'player_5', 'player_1'] }, actor: null, action_type: null, system_name: 'speaking_order_announced' },
  { event_id: 'demo-1500', match_id: DEMO_MATCH_ID, seq: 1500, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1500, payload: { speaker: 'player_5', content: 'player_0 走的时候没有给出任何能盘通的逻辑，现在场上最像补位狼的是一直煽动转票的 player_2。' }, actor: null, action_type: null, system_name: 'speech_delivered' },
  { event_id: 'demo-1600', match_id: DEMO_MATCH_ID, seq: 1600, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1600, payload: { message: 'player_4 voted for player_2', voter: 'player_4', target: 'player_2' }, actor: null, action_type: null, system_name: 'vote_recorded' },
  { event_id: 'demo-1700', match_id: DEMO_MATCH_ID, seq: 1700, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1700, payload: { message: 'player_5 voted for player_2', voter: 'player_5', target: 'player_2' }, actor: null, action_type: null, system_name: 'vote_recorded' },
  { event_id: 'demo-1800', match_id: DEMO_MATCH_ID, seq: 1800, type: 'system', phase: 'day_2', visibility: ['all'], ts: 1800, payload: { eliminated_player: 'player_2', reason: 'eliminated by vote' }, actor: null, action_type: null, system_name: 'player_eliminated' },
  { event_id: 'demo-1900', match_id: DEMO_MATCH_ID, seq: 1900, type: 'system', phase: 'post_game', visibility: ['all'], ts: 1900, payload: { winner: 'villagers', final_alive_players: ['player_1', 'player_4', 'player_5'] }, actor: null, action_type: null, system_name: 'game_ended' },
]

function deepClone(value) {
  return JSON.parse(JSON.stringify(value))
}

function computeStats(events) {
  const countsByType = {}
  const countsByPhase = {}
  const countsBySystemName = {}
  const countsByActor = {}

  for (const event of events) {
    countsByType[event.type] = (countsByType[event.type] ?? 0) + 1
    countsByPhase[event.phase] = (countsByPhase[event.phase] ?? 0) + 1
    if (event.system_name) countsBySystemName[event.system_name] = (countsBySystemName[event.system_name] ?? 0) + 1
    if (event.actor) countsByActor[event.actor] = (countsByActor[event.actor] ?? 0) + 1
  }

  return {
    match_id: DEMO_MATCH_ID,
    total_events: events.length,
    first_seq: events[0]?.seq ?? 0,
    last_seq: events.at(-1)?.seq ?? 0,
    counts_by_type: countsByType,
    counts_by_phase: countsByPhase,
    counts_by_system_name: countsBySystemName,
    counts_by_actor: countsByActor,
  }
}

const demoStats = computeStats(demoTimeline)
const demoSnapshotEvents = demoTimeline.slice(0, 3)

export function isDemoMatchId(matchId) {
  return matchId === DEMO_MATCH_ID
}

export function getDemoMatches() {
  return {
    items: [{ match_id: DEMO_MATCH_ID, phase: 'day_1', status: 'running', winner: null, total_events: demoTimeline.length, last_seq: demoTimeline.at(-1)?.seq ?? 0 }],
  }
}

export function getDemoSnapshot(matchId) {
  if (!isDemoMatchId(matchId)) throw new Error(`unknown demo match: ${matchId}`)

  return {
    match: { match_id: DEMO_MATCH_ID, status: 'running', phase: 'day_1', current_subphase: 'discussion', alive_players_count: demoPlayers.length, total_players: demoPlayers.length, current_speaker: null, focus_target: null, winner: null, game_ended: false },
    players: deepClone(demoPlayers),
    recent_events: deepClone(demoSnapshotEvents),
  }
}

export function getDemoEvents(matchId, afterSeq = 0, limit = 2) {
  if (!isDemoMatchId(matchId)) throw new Error(`unknown demo match: ${matchId}`)

  const events = demoTimeline.filter((event) => event.seq > afterSeq).slice(0, limit)
  const lastSeq = events.at(-1)?.seq ?? afterSeq

  return {
    match_id: DEMO_MATCH_ID,
    next_seq: lastSeq,
    has_more: demoTimeline.some((event) => event.seq > lastSeq),
    events: deepClone(events),
  }
}

export function getDemoTimeline(matchId) {
  if (!isDemoMatchId(matchId)) throw new Error(`unknown demo match: ${matchId}`)
  return deepClone(demoTimeline)
}

export function getDemoStats(matchId) {
  if (!isDemoMatchId(matchId)) throw new Error(`unknown demo match: ${matchId}`)
  return deepClone(demoStats)
}
