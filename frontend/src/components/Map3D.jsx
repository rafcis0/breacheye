import { useEffect, useRef } from 'react'

const API_URL = '/api/map/point-cloud/latest'
const MAX_POINTS = 12000

function fallbackCloud() {
  const points = []
  for (let i = 0; i < 900; i += 1) {
    const t = i / 900
    const angle = t * Math.PI * 10
    const radius = 0.16 + t * 0.38
    points.push({
      x: Math.cos(angle) * radius,
      y: (t - 0.5) * 0.85,
      z: Math.sin(angle) * radius * 0.55,
      intensity: 0.35 + t * 0.55,
    })
  }
  return { source: 'waiting_for_reconstruction', points }
}

function cloudToGeometry(THREE, cloud) {
  const points = Array.isArray(cloud?.points) ? cloud.points.slice(0, MAX_POINTS) : []
  const positions = new Float32Array(points.length * 3)
  const colors = new Float32Array(points.length * 3)
  for (let i = 0; i < points.length; i += 1) {
    const point = points[i]
    positions[i * 3] = Number(point.x) || 0
    positions[i * 3 + 1] = Number(point.z) || 0
    positions[i * 3 + 2] = Number(point.y) || 0
    if (point.r !== undefined && point.g !== undefined && point.b !== undefined) {
      colors[i * 3] = Math.max(0, Math.min(1, Number(point.r)))
      colors[i * 3 + 1] = Math.max(0, Math.min(1, Number(point.g)))
      colors[i * 3 + 2] = Math.max(0, Math.min(1, Number(point.b)))
    } else {
      const intensity = Math.max(0.15, Math.min(1, Number(point.intensity) || 0.5))
      colors[i * 3] = 0.25 + intensity * 0.45
      colors[i * 3 + 1] = 0.55 + intensity * 0.35
      colors[i * 3 + 2] = 0.95
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  geometry.computeBoundingSphere()
  return geometry
}

export default function Map3D() {
  const rootRef = useRef(null)
  const pointsRef = useRef(null)
  const rendererRef = useRef(null)
  const labelRef = useRef(null)
  const threeRef = useRef(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return undefined

    let running = true
    let ro
    let renderer
    let material
    let grid
    let axes

    import('three').then((THREE) => {
      if (!running) return
      threeRef.current = THREE

      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0x08090d)

      const camera = new THREE.PerspectiveCamera(48, 1, 0.01, 100)
      camera.position.set(0.9, 0.75, 1.4)
      camera.lookAt(0, 0, 0)

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      rendererRef.current = renderer
      root.appendChild(renderer.domElement)

      grid = new THREE.GridHelper(1.6, 12, 0x2dd4bf, 0x1f2937)
      grid.rotation.x = Math.PI / 2
      scene.add(grid)

      axes = new THREE.AxesHelper(0.35)
      scene.add(axes)

      material = new THREE.PointsMaterial({
        size: 0.012,
        vertexColors: true,
        transparent: true,
        opacity: 0.92,
        depthWrite: false,
      })
      pointsRef.current = new THREE.Points(cloudToGeometry(THREE, fallbackCloud()), material)
      scene.add(pointsRef.current)

      const resize = () => {
        const width = root.clientWidth || 320
        const height = root.clientHeight || 220
        renderer.setSize(width, height, false)
        camera.aspect = width / height
        camera.updateProjectionMatrix()
      }
      resize()
      ro = new ResizeObserver(resize)
      ro.observe(root)

      const render = () => {
        if (!running) return
        if (pointsRef.current) {
          pointsRef.current.rotation.y += 0.003
        }
        renderer.render(scene, camera)
        requestAnimationFrame(render)
      }
      render()
    })

    return () => {
      running = false
      ro?.disconnect()
      renderer?.dispose()
      material?.dispose()
      grid?.geometry.dispose()
      axes?.geometry.dispose()
      pointsRef.current?.geometry.dispose()
      if (renderer?.domElement.parentNode === root) {
        root.removeChild(renderer.domElement)
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function loadCloud() {
      try {
        const response = await fetch(API_URL, { cache: 'no-store' })
        if (!response.ok) throw new Error(`status ${response.status}`)
        const cloud = await response.json()
        if (cancelled || !pointsRef.current || !threeRef.current) return
        const next = cloudToGeometry(threeRef.current, cloud)
        const prev = pointsRef.current.geometry
        pointsRef.current.geometry = next
        prev.dispose()
        if (labelRef.current) {
          labelRef.current.textContent = `${cloud.source || 'point_cloud'} · ${cloud.points?.length ?? 0} pts`
        }
      } catch {
        if (labelRef.current) {
          labelRef.current.textContent = 'waiting for 3D reconstruction'
        }
      }
    }

    loadCloud()
    const timer = setInterval(loadCloud, 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return (
    <div className="map3d">
      <div className="map3d__header">
        <span className="map3d__title">3D RECON</span>
        <span ref={labelRef} className="map3d__status">waiting for 3D reconstruction</span>
      </div>
      <div ref={rootRef} className="map3d__viewport" />
    </div>
  )
}
