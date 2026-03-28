import { Suspense, useEffect, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Clone, Html, OrbitControls, QuadraticBezierLine, Sparkles, useGLTF, useTexture } from '@react-three/drei'
import * as THREE from 'three'
import { formatPhaseLabel, getMoodFromPhase, getPlayerColor, getSeatPosition, shortPlayerName } from '../lib/gameState'
import { logInfo, logWarn } from '../lib/runtimeLogger'

const MODEL_PATHS = {
  campfire: '/assets/kenney/survival-kit/Models/GLB format/campfire-pit.glb',
  barrel: '/assets/kenney/survival-kit/Models/GLB format/barrel.glb',
  tent: '/assets/kenney/survival-kit/Models/GLB format/tent.glb',
  tree: '/assets/kenney/survival-kit/Models/GLB format/tree-autumn.glb',
  treeTall: '/assets/kenney/survival-kit/Models/GLB format/tree-autumn-tall.glb',
  rockA: '/assets/kenney/survival-kit/Models/GLB format/rock-a.glb',
  rockB: '/assets/kenney/survival-kit/Models/GLB format/rock-b.glb',
}

const ICON_PATHS = {
  character: '/assets/kenney/board-game-icons/PNG/Default (64px)/character.png',
  crown: '/assets/kenney/board-game-icons/PNG/Default (64px)/crown_a.png',
  skull: '/assets/kenney/board-game-icons/PNG/Default (64px)/cards_skull.png',
  target: '/assets/kenney/board-game-icons/PNG/Default (64px)/card_target.png',
}

function normalizeAngle(angle) {
  let next = angle
  while (next > Math.PI) next -= Math.PI * 2
  while (next < -Math.PI) next += Math.PI * 2
  return next
}

function dampAngle(current, target, lambda, delta) {
  return current + normalizeAngle(target - current) * (1 - Math.exp(-lambda * delta))
}

function clampSpherical(spherical) {
  spherical.radius = THREE.MathUtils.clamp(spherical.radius, 6.4, 15.8)
  spherical.phi = THREE.MathUtils.clamp(spherical.phi, 0.72, 1.32)
  return spherical
}

function ScenePlaceholder() {
  return (
    <div className="scene-empty">
      <div className="scene-empty__halo" />
      <div className="scene-empty__ring">
        {Array.from({ length: 6 }).map((_, index) => (
          <span key={index} className="scene-empty__seat" />
        ))}
      </div>
      <div className="scene-empty__copy">
        <p className="eyebrow">Observer Boot</p>
        <strong>等待对局数据…</strong>
        <span>快照和 3D 素材准备完成后，这里会切换到营火审判场。</span>
      </div>
    </div>
  )
}

function StaticModel({ path, position, rotation = [0, 0, 0], scale = 1 }) {
  const gltf = useGLTF(path)

  return (
    <group position={position} rotation={rotation} scale={scale}>
      <Clone object={gltf.scene} castShadow receiveShadow />
    </group>
  )
}

function IconBillboard({ path, color, position, scale }) {
  const texture = useTexture(path)

  return (
    <sprite position={position} scale={[scale, scale, 1]}>
      <spriteMaterial map={texture} transparent color={color} depthWrite={false} />
    </sprite>
  )
}

function PlayerTotem({ player, totalPlayers, selected, badgeHolder, onSelectPlayer }) {
  const groupRef = useRef(null)
  const basePosition = getSeatPosition(player.seat_no, totalPlayers)
  const color = getPlayerColor(player)
  const isDead = !player.alive

  useFrame((state, delta) => {
    if (!groupRef.current) return

    const lift = isDead
      ? -0.28
      : player.is_speaking
        ? 0.14 + Math.sin(state.clock.elapsedTime * 5) * 0.08
        : selected
          ? 0.08 + Math.sin(state.clock.elapsedTime * 3) * 0.05
          : Math.sin(state.clock.elapsedTime * 1.8 + player.seat_no) * 0.02

    groupRef.current.position.x = basePosition[0]
    groupRef.current.position.y = THREE.MathUtils.lerp(groupRef.current.position.y, lift, 1 - Math.exp(-delta * 5))
    groupRef.current.position.z = basePosition[2]
    groupRef.current.rotation.y += delta * (player.is_speaking ? 0.65 : 0.12)
  })

  return (
    <group
      ref={groupRef}
      onClick={() => onSelectPlayer(player.id)}
      onPointerDown={(event) => {
        event.stopPropagation()
      }}
    >
      <mesh position={[0, 0.2, 0]} receiveShadow castShadow>
        <cylinderGeometry args={[0.95, 1.12, 0.22, 20]} />
        <meshStandardMaterial color={isDead ? '#463d38' : '#2f241f'} roughness={0.96} />
      </mesh>

      <mesh position={[0, 0.95, 0]} receiveShadow castShadow>
        <cylinderGeometry args={[0.38, 0.48, 1.45, 7]} />
        <meshStandardMaterial
          color={isDead ? '#4f4942' : color}
          emissive={isDead ? '#100d0c' : selected || player.is_speaking ? color : '#1b1815'}
          emissiveIntensity={isDead ? 0.1 : selected ? 0.7 : player.is_speaking ? 0.5 : 0.2}
          roughness={0.42}
          metalness={0.12}
        />
      </mesh>

      <mesh position={[0, 1.95, 0]} castShadow>
        <octahedronGeometry args={[0.34, 0]} />
        <meshStandardMaterial
          color={isDead ? '#6d655b' : '#f0d7a2'}
          emissive={isDead ? '#1c1712' : '#8f6332'}
          emissiveIntensity={selected ? 0.5 : 0.2}
          roughness={0.28}
          metalness={0.32}
        />
      </mesh>

      <IconBillboard path={isDead ? ICON_PATHS.skull : ICON_PATHS.character} position={[0, 2.65, 0]} color={isDead ? '#d5b69b' : '#fff4d8'} scale={selected ? 0.92 : 0.76} />

      {player.vote_target ? <IconBillboard path={ICON_PATHS.target} position={[0.82, 1.7, 0]} color="#ffd26f" scale={0.42} /> : null}
      {badgeHolder === player.id ? <IconBillboard path={ICON_PATHS.crown} position={[0, 3.2, 0]} color="#ffdc86" scale={0.7} /> : null}

      <Html position={[0, 3.58, 0]} center distanceFactor={15}>
        <div className={`seat-tag ${selected ? 'is-selected' : ''}`}>
          <span>{shortPlayerName(player.id)}</span>
          <span>{isDead ? '已出局' : player.is_speaking ? '发言中' : '在席'}</span>
        </div>
      </Html>
    </group>
  )
}

function VoteLines({ players, totalPlayers, selectedPlayerId }) {
  const playerPositions = Object.fromEntries(players.map((player) => [player.id, getSeatPosition(player.seat_no, totalPlayers)]))

  return players
    .filter((player) => player.vote_target && playerPositions[player.vote_target])
    .map((player) => {
      const start = playerPositions[player.id]
      const end = playerPositions[player.vote_target]
      const highlighted = player.id === selectedPlayerId || player.vote_target === selectedPlayerId

      return (
        <QuadraticBezierLine
          key={`${player.id}-${player.vote_target}`}
          start={[start[0], 1.65, start[2]]}
          end={[end[0], 1.65, end[2]]}
          mid={[(start[0] + end[0]) / 2, 3.1, (start[2] + end[2]) / 2]}
          color={highlighted ? '#f6cb66' : '#8ae7db'}
          lineWidth={highlighted ? 4.6 : 2.4}
          transparent
          opacity={highlighted ? 1 : 0.62}
        />
      )
    })
}

function CameraRig({ focusPosition, autoOrbit, command }) {
  const controlsRef = useRef(null)
  const targetRef = useRef(new THREE.Vector3(0, 1.35, 0))
  const { camera } = useThree()
  const desiredSphericalRef = useRef(new THREE.Spherical(11.8, 1.02, Math.PI * 0.18))
  const currentSphericalRef = useRef(new THREE.Spherical(11.8, 1.02, Math.PI * 0.18))
  const offsetRef = useRef(new THREE.Vector3(11, 7, 11))
  const desiredPositionRef = useRef(new THREE.Vector3(11, 7, 11))
  const focusRef = useRef(new THREE.Vector3(0, 1.35, 0))
  const isInteractingRef = useRef(false)
  const handledCommandIdRef = useRef(null)

  function captureCurrentOrbit() {
    if (!controlsRef.current) return
    offsetRef.current.copy(camera.position).sub(controlsRef.current.target)
    currentSphericalRef.current.setFromVector3(offsetRef.current)
    desiredSphericalRef.current.copy(clampSpherical(currentSphericalRef.current.clone()))
  }

  useFrame((state, delta) => {
    focusRef.current.set(
      focusPosition ? focusPosition[0] : 0,
      focusPosition ? 1.8 : 1.35,
      focusPosition ? focusPosition[2] : 0,
    )
    targetRef.current.lerp(focusRef.current, 1 - Math.exp(-delta * 2.9))

    const baseAngle = focusPosition ? Math.atan2(focusPosition[2], focusPosition[0]) : Math.PI * 0.18
    const defaultRadius = focusPosition ? 8.9 : 11.4
    const defaultPhi = focusPosition ? 0.96 : 1.02

    if (command && handledCommandIdRef.current !== command.id) {
      handledCommandIdRef.current = command.id

      if (command.type === 'reset') {
        desiredSphericalRef.current.set(defaultRadius, defaultPhi, baseAngle + 0.92)
      } else if (command.type === 'focus') {
        desiredSphericalRef.current.set(Math.max(defaultRadius - 0.9, 7.1), 0.92, baseAngle + 0.86)
      } else if (command.type === 'zoom-in') {
        desiredSphericalRef.current.radius *= 0.84
      } else if (command.type === 'zoom-out') {
        desiredSphericalRef.current.radius *= 1.16
      }

      clampSpherical(desiredSphericalRef.current)
    }

    if (autoOrbit && !isInteractingRef.current) {
      desiredSphericalRef.current.radius = THREE.MathUtils.damp(desiredSphericalRef.current.radius, defaultRadius, 3.6, delta)
      desiredSphericalRef.current.phi = THREE.MathUtils.damp(desiredSphericalRef.current.phi, defaultPhi, 3.6, delta)
      desiredSphericalRef.current.theta = baseAngle + 0.92 + state.clock.elapsedTime * 0.14
    }

    clampSpherical(desiredSphericalRef.current)

    currentSphericalRef.current.radius = THREE.MathUtils.damp(currentSphericalRef.current.radius, desiredSphericalRef.current.radius, 4.2, delta)
    currentSphericalRef.current.phi = THREE.MathUtils.damp(currentSphericalRef.current.phi, desiredSphericalRef.current.phi, 4.2, delta)
    currentSphericalRef.current.theta = dampAngle(currentSphericalRef.current.theta, desiredSphericalRef.current.theta, 4.2, delta)

    desiredPositionRef.current.setFromSpherical(currentSphericalRef.current).add(targetRef.current)
    camera.position.lerp(desiredPositionRef.current, 1 - Math.exp(-delta * 5.2))

    if (controlsRef.current) {
      controlsRef.current.target.copy(targetRef.current)
      controlsRef.current.update()
    }
  })

  return (
    <OrbitControls
      ref={controlsRef}
      enablePan={false}
      enableDamping
      dampingFactor={0.08}
      minDistance={6.4}
      maxDistance={15.8}
      minPolarAngle={0.72}
      maxPolarAngle={1.32}
      onStart={() => {
        isInteractingRef.current = true
      }}
      onEnd={() => {
        isInteractingRef.current = false
        captureCurrentOrbit()
      }}
      onChange={() => {
        if (!controlsRef.current || !isInteractingRef.current) return
        offsetRef.current.copy(camera.position).sub(controlsRef.current.target)
        currentSphericalRef.current.setFromVector3(offsetRef.current)
        desiredSphericalRef.current.copy(clampSpherical(currentSphericalRef.current.clone()))
      }}
    />
  )
}

function SceneDiagnostics() {
  const { gl } = useThree()

  useEffect(() => {
    const canvas = gl.domElement
    const handleContextLost = (event) => {
      event.preventDefault()
      logWarn('scene.webgl', 'WebGL context lost')
    }
    const handleContextRestored = () => {
      logInfo('scene.webgl', 'WebGL context restored')
    }

    canvas.addEventListener('webglcontextlost', handleContextLost)
    canvas.addEventListener('webglcontextrestored', handleContextRestored)

    logInfo('scene.webgl', '3D scene mounted', {
      antialias: gl.getContextAttributes?.().antialias ?? null,
      alpha: gl.getContextAttributes?.().alpha ?? null,
    })

    return () => {
      canvas.removeEventListener('webglcontextlost', handleContextLost)
      canvas.removeEventListener('webglcontextrestored', handleContextRestored)
    }
  }, [gl])

  return null
}

function CouncilScene({ session, selectedPlayerId, onSelectPlayer, autoOrbit, cameraCommand }) {
  const mood = getMoodFromPhase(session.phase)
  const totalPlayers = session.match.total_players || session.players.length
  const focusPlayer =
    session.players.find((player) => player.id === selectedPlayerId) ??
    session.players.find((player) => player.id === session.currentSpeaker) ??
    session.players.find((player) => player.id === session.focusTarget) ??
    null
  const focusPosition = focusPlayer ? getSeatPosition(focusPlayer.seat_no, totalPlayers) : null

  return (
    <>
      <color attach="background" args={[mood.background]} />
      <fog attach="fog" args={[mood.fog, 10, 28]} />

      <hemisphereLight color={mood.ambient} groundColor={mood.ring} intensity={mood.ambientIntensity} />
      <directionalLight position={[6, 9, 2]} intensity={mood.moonIntensity} color={mood.moon} castShadow shadow-mapSize-width={2048} shadow-mapSize-height={2048} />
      <pointLight position={[0, 1.6, 0]} intensity={mood.fireIntensity} color={mood.fire} distance={18} castShadow />
      <spotLight position={[0, 5, 0]} intensity={2.4} distance={18} color="#ffd8a4" angle={0.55} penumbra={0.7} />

      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[9.4, 64]} />
        <meshStandardMaterial color={mood.ground} roughness={1} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]} receiveShadow>
        <ringGeometry args={[9.5, 14.5, 64]} />
        <meshStandardMaterial color={mood.ring} roughness={1} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]} receiveShadow>
        <ringGeometry args={[6.2, 7.8, 64]} />
        <meshStandardMaterial color={mood.haze} roughness={0.95} />
      </mesh>

      <Suspense fallback={null}>
        <StaticModel path={MODEL_PATHS.campfire} position={[0, 0.04, 0]} scale={1.45} />
        <StaticModel path={MODEL_PATHS.tent} position={[-7.4, 0, -5.8]} rotation={[0, Math.PI * 0.2, 0]} scale={1.5} />
        <StaticModel path={MODEL_PATHS.barrel} position={[-6.3, 0, -4.1]} rotation={[0, Math.PI * 0.1, 0]} scale={0.85} />
        <StaticModel path={MODEL_PATHS.rockA} position={[6.9, 0, -5.5]} rotation={[0, Math.PI * 0.34, 0]} scale={1.25} />
        <StaticModel path={MODEL_PATHS.rockB} position={[7.4, 0, 4.8]} rotation={[0, Math.PI * 0.15, 0]} scale={1.1} />
        <StaticModel path={MODEL_PATHS.tree} position={[-10.8, 0, -1.8]} rotation={[0, Math.PI * 0.4, 0]} scale={1.65} />
        <StaticModel path={MODEL_PATHS.treeTall} position={[-9.6, 0, 6.4]} rotation={[0, Math.PI * 0.22, 0]} scale={1.8} />
        <StaticModel path={MODEL_PATHS.treeTall} position={[9.8, 0, 6.6]} rotation={[0, Math.PI * 0.52, 0]} scale={1.75} />
        <StaticModel path={MODEL_PATHS.tree} position={[11.1, 0, -2.6]} rotation={[0, Math.PI * 0.3, 0]} scale={1.55} />

        {session.players.map((player) => {
          const barrelPosition = getSeatPosition(player.seat_no, totalPlayers)

          return (
            <group key={player.id}>
              <StaticModel path={MODEL_PATHS.barrel} position={[barrelPosition[0], 0, barrelPosition[2]]} rotation={[0, player.seat_no * 0.18, 0]} scale={0.78} />
              <PlayerTotem player={player} totalPlayers={totalPlayers} selected={player.id === selectedPlayerId} badgeHolder={session.badgeHolder} onSelectPlayer={onSelectPlayer} />
            </group>
          )
        })}
      </Suspense>

      <VoteLines players={session.players} totalPlayers={totalPlayers} selectedPlayerId={selectedPlayerId} />

      <Sparkles count={36} scale={[2.4, 1.7, 2.4]} position={[0, 1.55, 0]} size={4} color="#ffcf74" />

      <Html position={[0, 4.7, 0]} center distanceFactor={18}>
        <div className="phase-flare">
          <span>{formatPhaseLabel(session.phase)}</span>
          <span>{session.gameEnded ? '终局结算' : '营火审判场'}</span>
        </div>
      </Html>

      <CameraRig focusPosition={focusPosition} autoOrbit={autoOrbit} command={cameraCommand} />
    </>
  )
}

export function WerewolfScene({ session, selectedPlayerId, onSelectPlayer, autoOrbit, cameraCommand }) {
  if (!session) return <ScenePlaceholder />

  return (
    <div className="canvas-shell">
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        camera={{ fov: 42, near: 0.1, far: 100, position: [11, 7, 11] }}
      >
        <SceneDiagnostics />
        <CouncilScene
          session={session}
          selectedPlayerId={selectedPlayerId}
          onSelectPlayer={onSelectPlayer}
          autoOrbit={autoOrbit}
          cameraCommand={cameraCommand}
        />
      </Canvas>
    </div>
  )
}

Object.values(MODEL_PATHS).forEach((path) => useGLTF.preload(path))
