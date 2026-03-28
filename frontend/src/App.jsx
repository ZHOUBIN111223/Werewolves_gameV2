import { Suspense, lazy, useDeferredValue, useEffect, useEffectEvent, useState } from 'react'
import './App.css'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { applyEventsSequentially, createSessionFromSnapshot, formatPhaseLabel, formatSubphaseLabel, formatWinnerLabel, getEventAnchorId, shortPlayerName, summarizeEvent } from './lib/gameState'
import { useWerewolfObserver } from './hooks/useWerewolfObserver'

const WerewolfScene = lazy(() =>
  import('./components/WerewolfScene').then((module) => ({
    default: module.WerewolfScene,
  })),
)

const UI_ASSETS = {
  campfire: '/assets/kenney/board-game-icons/PNG/Default (64px)/campfire.png',
  crown: '/assets/kenney/board-game-icons/PNG/Default (64px)/crown_a.png',
  skull: '/assets/kenney/board-game-icons/PNG/Default (64px)/cards_skull.png',
  arrow: '/assets/kenney/board-game-icons/PNG/Default (64px)/arrow_right_curve.png',
  award: '/assets/kenney/board-game-icons/PNG/Default (64px)/award.png',
}

const AUDIO_ASSETS = {
  uiClick: '/assets/kenney/ui-audio/Audio/click3.ogg',
  uiToggle: '/assets/kenney/ui-audio/Audio/switch14.ogg',
  phase: '/assets/kenney/ui-audio/Audio/switch21.ogg',
  vote: '/assets/kenney/ui-audio/Audio/click5.ogg',
  speech: '/assets/kenney/ui-audio/Audio/rollover4.ogg',
  elimination: '/assets/kenney/rpg-audio/Audio/knifeSlice2.ogg',
  ending: '/assets/kenney/rpg-audio/Audio/bookClose.ogg',
}

function describeScene(session) {
  if (!session) return '等待营火点亮。'
  if (session.gameEnded) return `${formatWinnerLabel(session.winner)} 已锁定胜局，篝火边只剩最后的结算低语。`
  if (session.currentSpeaker) return `${shortPlayerName(session.currentSpeaker)} 正在掌控话语权，其他席位的票型与姿态会围绕他重新对齐。`
  if (session.focusTarget) return `${shortPlayerName(session.focusTarget)} 成为当前焦点，观察周围投票弧线和灯光变化。`
  return `${formatPhaseLabel(session.phase)} / ${formatSubphaseLabel(session.subphase)}，场上仍有 ${session.match.alive_players_count} 人在席。`
}

function getSoundForEvent(event) {
  switch (event?.system_name) {
    case 'phase_advanced':
      return AUDIO_ASSETS.phase
    case 'vote_recorded':
    case 'sheriff_vote_recorded':
      return AUDIO_ASSETS.vote
    case 'speech_delivered':
      return AUDIO_ASSETS.speech
    case 'player_eliminated':
    case 'night_deaths_announced':
      return AUDIO_ASSETS.elimination
    case 'game_ended':
      return AUDIO_ASSETS.ending
    default:
      return null
  }
}

function numericEntries(record) {
  return Object.entries(record ?? {}).sort((left, right) => right[1] - left[1])
}

function playAudioClip(enabled, path, volume = 0.35) {
  if (!enabled || !path) return
  const audio = new Audio(path)
  audio.volume = volume
  audio.play().catch(() => {})
}

function StatBars({ items, total }) {
  return items.map(([label, value]) => (
    <div className="stat-bar" key={label}>
      <div className="stat-bar__row">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      <div className="stat-bar__track">
        <div className="stat-bar__fill" style={{ width: `${Math.max((value / Math.max(total, 1)) * 100, 8)}%` }} />
      </div>
    </div>
  ))
}

function ConnectionPill({ source, connection }) {
  const label = source === 'demo' ? 'DEMO' : source === 'live' ? 'LIVE' : 'BOOT'

  return (
    <div className={`status-pill is-${connection.state}`}>
      <span>{label}</span>
      <span>{connection.label}</span>
    </div>
  )
}

function RuntimeAlert({ connection, source }) {
  if (!connection?.state || connection.state === 'online') return null

  const title =
    connection.state === 'demo'
      ? '实时后端不可用，当前已切到 Demo 对局'
      : connection.state === 'connecting'
        ? '正在连接观战后端'
        : '实时连接中断，当前界面可能只显示部分信息'

  return (
    <div className={`runtime-alert is-${connection.state}`}>
      <div>
        <p className="eyebrow">Runtime Status</p>
        <strong>{title}</strong>
      </div>
      <p>{connection.label}{source === 'demo' ? '，3D 场景和面板仍可继续查看。' : '，详细错误已写入运行日志。'}</p>
    </div>
  )
}

function SceneFallbackCard({ session, error, reset }) {
  const players = session?.players ?? []

  return (
    <div className="scene-fallback">
      <div className="scene-fallback__copy">
        <p className="eyebrow">Scene Fallback</p>
        <h2>3D 场景没有正常渲染</h2>
        <p>
          这通常是 WebGL、模型加载或运行时异常导致的。错误已经写入日志，当前先切回可见的 2D 失败态，避免整块区域直接变黑。
        </p>
        <p className="boundary-error">{error?.message ?? 'Unknown scene error'}</p>
        <div className="boundary-actions">
          <button type="button" className="toolbar-button is-active" onClick={reset}>
            重新加载场景
          </button>
        </div>
      </div>

      <div className="scene-fallback__grid">
        <div className="scene-fallback__card">
          <span>当前阶段</span>
          <strong>{session ? formatPhaseLabel(session.phase) : '未知'}</strong>
        </div>
        <div className="scene-fallback__card">
          <span>当前子阶段</span>
          <strong>{session ? formatSubphaseLabel(session.subphase) : '未知'}</strong>
        </div>
        <div className="scene-fallback__card">
          <span>在席人数</span>
          <strong>{players.filter((player) => player.alive).length}</strong>
        </div>
        <div className="scene-fallback__card">
          <span>总席位</span>
          <strong>{players.length}</strong>
        </div>
      </div>

      <div className="scene-fallback__seats">
        {players.map((player) => (
          <div key={player.id} className={`scene-fallback__seat ${player.alive ? '' : 'is-dead'}`}>
            <strong>{player.name}</strong>
            <span>座位 {player.seat_no}</span>
            <span>{player.alive ? '在席' : '已出局'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function App() {
  const observerState = useWerewolfObserver()

  return (
    <AppErrorBoundary
      scope="workspace"
      title="观战界面渲染失败"
      description="主界面发生异常。日志已经保存，点击按钮可以直接重试。"
    >
      <MatchWorkspace
        key={observerState.selectedMatchId ?? 'no-match'}
        {...observerState}
      />
    </AppErrorBoundary>
  )
}

function MatchWorkspace({
  source,
  matches,
  selectedMatchId,
  setSelectedMatchId,
  snapshot,
  liveSession,
  stats,
  eventFeed,
  timeline,
  timelineLoading,
  loading,
  connection,
  ensureTimeline,
  refreshMatches,
}) {
  const [manualSelectedPlayerId, setManualSelectedPlayerId] = useState(null)
  const [autoOrbit, setAutoOrbit] = useState(true)
  const [audioEnabled, setAudioEnabled] = useState(false)
  const [replayMode, setReplayMode] = useState(false)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayPlaying, setReplayPlaying] = useState(false)
  const [cameraCommand, setCameraCommand] = useState(null)

  const deferredEventFeed = useDeferredValue(eventFeed)
  const latestEventId = deferredEventFeed[0]?.event_id

  const playbackSession =
    replayMode && snapshot && timeline.length
      ? applyEventsSequentially(createSessionFromSnapshot(snapshot, { freshPlayers: true }), timeline.slice(0, replayIndex))
      : null

  const sceneSession = playbackSession ?? liveSession
  const fallbackSelectedPlayerId =
    sceneSession?.currentSpeaker ??
    sceneSession?.focusTarget ??
    sceneSession?.players.find((player) => player.alive)?.id ??
    sceneSession?.players[0]?.id ??
    null

  const selectedPlayerId =
    sceneSession?.players.some((player) => player.id === manualSelectedPlayerId)
      ? manualSelectedPlayerId
      : fallbackSelectedPlayerId

  const selectedPlayer = sceneSession?.players.find((player) => player.id === selectedPlayerId) ?? null
  const latestSpeech = sceneSession?.speechLog?.[0] ?? null
  const topSystems = numericEntries(stats?.counts_by_system_name).slice(0, 4)
  const topActors = numericEntries(stats?.counts_by_actor).slice(0, 4)

  useEffect(() => {
    if (!latestEventId) return

    const sound = getSoundForEvent(deferredEventFeed[0])
    const volume =
      deferredEventFeed[0]?.system_name === 'game_ended'
        ? 0.5
        : deferredEventFeed[0]?.system_name === 'player_eliminated'
          ? 0.45
          : 0.25

    playAudioClip(audioEnabled, sound, volume)
  }, [latestEventId, audioEnabled, deferredEventFeed])

  const stepReplayForward = useEffectEvent(() => {
    setReplayIndex((current) => {
      if (current >= timeline.length) {
        setReplayPlaying(false)
        return timeline.length
      }

      const next = Math.min(current + 1, timeline.length)
      if (next >= timeline.length) setReplayPlaying(false)
      return next
    })
  })

  useEffect(() => {
    if (!replayMode || !replayPlaying || !timeline.length) return undefined

    const timer = window.setInterval(() => {
      stepReplayForward()
    }, 1100)

    return () => {
      window.clearInterval(timer)
    }
  }, [replayMode, replayPlaying, timeline.length])

  async function toggleReplayMode() {
    playAudioClip(audioEnabled, AUDIO_ASSETS.uiToggle, 0.28)

    if (replayMode) {
      setReplayMode(false)
      setReplayPlaying(false)
      return
    }

    const timelineItems = await ensureTimeline()
    setReplayMode(true)
    setReplayIndex(timelineItems.length)
  }

  function toggleAudio() {
    setAudioEnabled((current) => !current)
  }

  function toggleOrbit() {
    playAudioClip(audioEnabled, AUDIO_ASSETS.uiToggle, 0.24)
    setAutoOrbit((current) => !current)
  }

  function issueCameraCommand(type) {
    playAudioClip(audioEnabled, AUDIO_ASSETS.uiClick, 0.2)
    if (type !== 'reset' && type !== 'follow') {
      setAutoOrbit(false)
    }

    setCameraCommand((current) => ({
      id: (current?.id ?? 0) + 1,
      type,
    }))
  }

  function refreshLobby() {
    playAudioClip(audioEnabled, AUDIO_ASSETS.uiClick, 0.24)
    refreshMatches(selectedMatchId)
  }

  function handleMatchSelect(matchId) {
    playAudioClip(audioEnabled, AUDIO_ASSETS.uiClick, 0.24)
    setSelectedMatchId(matchId)
  }

  function handlePlayerSelect(playerId) {
    playAudioClip(audioEnabled, AUDIO_ASSETS.uiClick, 0.18)
    setManualSelectedPlayerId(playerId)
    setAutoOrbit(false)
    setCameraCommand((current) => ({
      id: (current?.id ?? 0) + 1,
      type: 'focus',
    }))
  }

  function handleEventFocus(event) {
    const targetId = getEventAnchorId(event)
    if (targetId) {
      setManualSelectedPlayerId(targetId)
      setAutoOrbit(false)
      setCameraCommand((current) => ({
        id: (current?.id ?? 0) + 1,
        type: 'focus',
      }))
    }

    if (replayMode) {
      const eventIndex = timeline.findIndex((timelineEvent) => timelineEvent.event_id === event.event_id)
      if (eventIndex >= 0) setReplayIndex(eventIndex + 1)
    }
  }

  const aliveCount = sceneSession?.players.filter((player) => player.alive).length ?? 0
  const deathCount = (sceneSession?.players.length ?? 0) - aliveCount

  return (
    <div className="app-shell">
      <aside className="left-rail">
        <div className="brand-block">
          <div className="brand-mark">
            <img src={UI_ASSETS.campfire} alt="" />
          </div>
          <div>
            <p className="eyebrow">AI Werewolf Observer</p>
            <h1>Moonfire Court</h1>
            <p className="brand-copy">
              多智能体狼人杀的 3D 观战台。点击席位聚焦玩家，回放时间线，观察营火旁的票型与话术如何改变局势。
            </p>
          </div>
        </div>

        <ConnectionPill source={source} connection={connection} />

        <div className="side-section">
          <div className="section-heading">
            <span>对局大厅</span>
            <button type="button" className="ghost-button" onClick={refreshLobby}>
              刷新
            </button>
          </div>

          <div className="match-list">
            {matches.map((match) => (
              <button
                type="button"
                key={match.match_id}
                className={`match-pill ${match.match_id === selectedMatchId ? 'is-active' : ''}`}
                onClick={() => handleMatchSelect(match.match_id)}
              >
                <span>{match.match_id}</span>
                <span>{formatPhaseLabel(match.phase)} · {match.status === 'finished' ? '已结束' : '进行中'}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="side-section">
          <div className="section-heading">
            <span>总览指标</span>
            <img className="heading-icon" src={UI_ASSETS.award} alt="" />
          </div>

          <div className="metric-grid">
            <div className="metric-card"><span>在席</span><strong>{aliveCount}</strong></div>
            <div className="metric-card"><span>出局</span><strong>{deathCount}</strong></div>
            <div className="metric-card"><span>事件</span><strong>{stats?.total_events ?? 0}</strong></div>
            <div className="metric-card"><span>数据源</span><strong>{source === 'demo' ? 'Demo' : 'Live'}</strong></div>
          </div>
        </div>
      </aside>

      <main className="stage-column">
        <header className="stage-topbar">
          <div>
            <p className="eyebrow">当前阶段</p>
            <div className="phase-line">
              <strong>{sceneSession ? formatPhaseLabel(sceneSession.phase) : '等待中'}</strong>
              <span>{sceneSession ? formatSubphaseLabel(sceneSession.subphase) : '正在连接对局'}</span>
            </div>
          </div>

          <div className="toolbar">
            <button type="button" className={`toolbar-button ${autoOrbit ? 'is-active' : ''}`} onClick={toggleOrbit}>
              自动镜头
            </button>
            <button type="button" className="toolbar-button" onClick={() => issueCameraCommand('reset')}>
              归中
            </button>
            <button type="button" className="toolbar-button" onClick={() => issueCameraCommand('focus')}>
              聚焦席位
            </button>
            <button type="button" className="toolbar-button" onClick={() => issueCameraCommand('zoom-in')}>
              拉近
            </button>
            <button type="button" className="toolbar-button" onClick={() => issueCameraCommand('zoom-out')}>
              拉远
            </button>
            <button type="button" className={`toolbar-button ${audioEnabled ? 'is-active' : ''}`} onClick={toggleAudio}>
              {audioEnabled ? '音效已开' : '开启音效'}
            </button>
            <button type="button" className={`toolbar-button ${replayMode ? 'is-active' : ''}`} onClick={toggleReplayMode}>
              {replayMode ? '退出回放' : '进入回放'}
            </button>
          </div>
        </header>

        <RuntimeAlert connection={connection} source={source} />

        <section className="scene-panel">
          <AppErrorBoundary
            scope="scene"
            title="3D 场景渲染失败"
            description="场景资源或 WebGL 运行失败。错误已写入日志，当前显示 2D 失败态。"
            fallback={({ error, reset }) => <SceneFallbackCard session={sceneSession} error={error} reset={reset} />}
          >
            <Suspense fallback={<div className="scene-empty">加载 3D 场景…</div>}>
              <WerewolfScene
                session={sceneSession}
                selectedPlayerId={selectedPlayerId}
                onSelectPlayer={handlePlayerSelect}
                autoOrbit={autoOrbit}
                cameraCommand={cameraCommand}
              />
            </Suspense>
          </AppErrorBoundary>

          <div className="scene-copy">
            <p className="eyebrow">场景提示</p>
            <p>{describeScene(sceneSession)}</p>
          </div>

          {loading.match ? <div className="loading-mask">读取对局快照…</div> : null}
        </section>

        <section className="event-ribbon">
          <div className="section-heading">
            <span>公开事件流</span>
            <span className="subtle">
              {replayMode ? `回放进度 ${replayIndex}/${timeline.length || 0}` : loading.matches ? '加载大厅中' : '实时轮询公开事件'}
            </span>
          </div>

          <div className="event-track">
            {deferredEventFeed.map((event) => (
              <button type="button" key={event.event_id} className="event-chip" onClick={() => handleEventFocus(event)}>
                <span>{formatPhaseLabel(event.phase)}</span>
                <span>{summarizeEvent(event)}</span>
              </button>
            ))}
          </div>
        </section>
      </main>

      <aside className="right-rail">
        <div className="detail-panel">
          <div className="section-heading">
            <span>焦点席位</span>
            <img className="heading-icon" src={UI_ASSETS.crown} alt="" />
          </div>

          {selectedPlayer ? (
            <div className="player-focus">
              <div className="player-focus__name">
                <strong>{selectedPlayer.name}</strong>
                <span>座位 {selectedPlayer.seat_no}</span>
              </div>
              <div className="focus-tags">
                <span>{selectedPlayer.alive ? '仍在场' : '已出局'}</span>
                <span>{selectedPlayer.is_speaking ? '当前发言者' : '观察中'}</span>
                <span>{selectedPlayer.vote_target ? `票投 ${shortPlayerName(selectedPlayer.vote_target)}` : '尚未投票'}</span>
              </div>
              <div className="suspicion-block">
                <span>嫌疑热度</span>
                <div className="suspicion-track">
                  <div className="suspicion-fill" style={{ width: `${Math.min((selectedPlayer.suspicion ?? 0) * 100, 100)}%` }} />
                </div>
              </div>
            </div>
          ) : (
            <p className="empty-copy">点击 3D 场景中的席位以查看玩家状态。</p>
          )}
        </div>

        <div className="detail-panel">
          <div className="section-heading">
            <span>回放控制</span>
            <img className="heading-icon" src={UI_ASSETS.arrow} alt="" />
          </div>

          <div className="replay-controls">
            <button
              type="button"
              className="toolbar-button"
              disabled={!replayMode || !timeline.length}
              onClick={() => {
                playAudioClip(audioEnabled, AUDIO_ASSETS.uiClick, 0.22)
                setReplayPlaying((current) => !current)
              }}
            >
              {replayPlaying ? '暂停' : '播放'}
            </button>

            <button
              type="button"
              className="toolbar-button"
              disabled={!replayMode || !timeline.length}
              onClick={() => {
                playAudioClip(audioEnabled, AUDIO_ASSETS.uiClick, 0.22)
                setReplayPlaying(false)
                setReplayIndex(0)
              }}
            >
              重置
            </button>
          </div>

          <input
            className="timeline-slider"
            type="range"
            min="0"
            max={timeline.length}
            value={Math.min(replayIndex, timeline.length)}
            disabled={!replayMode || !timeline.length}
            onChange={(event) => {
              setReplayPlaying(false)
              setReplayIndex(Number(event.target.value))
            }}
          />

          <p className="subtle">
            {timelineLoading ? '时间线加载中…' : replayMode ? '拖动滑杆逐事件重建对局局面。' : '进入回放后可逐事件观看公开时间线。'}
          </p>
        </div>

        <div className="detail-panel">
          <div className="section-heading">
            <span>赛况统计</span>
            <img className="heading-icon" src={UI_ASSETS.skull} alt="" />
          </div>

          {stats ? (
            <>
              <div className="stats-group">
                <h2>系统事件热度</h2>
                <StatBars items={topSystems} total={stats.total_events} />
              </div>

              <div className="stats-group">
                <h2>行动参与度</h2>
                <StatBars items={topActors} total={stats.total_events} />
              </div>
            </>
          ) : (
            <p className="empty-copy">等待统计信息…</p>
          )}
        </div>

        <div className="detail-panel">
          <div className="section-heading">
            <span>最近发言</span>
            <img className="heading-icon" src={UI_ASSETS.campfire} alt="" />
          </div>

          {latestSpeech ? (
            <blockquote className="speech-card">
              <strong>{shortPlayerName(latestSpeech.speaker)}</strong>
              <p>{latestSpeech.content}</p>
            </blockquote>
          ) : (
            <p className="empty-copy">当前还没有可展示的公开发言。</p>
          )}
        </div>
      </aside>
    </div>
  )
}

export default App
