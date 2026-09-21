import { useEffect, useRef } from 'react'
import { demoPose } from '../lib/demo-motion'
import { useWebSocket } from '../contexts/WebSocketContext'

// Geometric bedroom analogue for the demo; no inference or recorded drone feed.
export default function DemoRoom() {
  const rootRef = useRef(null)
  const timeRef = useRef(0)
  const boxRef = useRef(null)
  const { data } = useWebSocket('drone.telemetry')
  timeRef.current = data?.demo_time_s ?? 0
  useEffect(() => {
    let disposed = false, renderer, observer, frame
    const resources = []
    import('three').then((T) => {
      if (disposed) return
      const root = rootRef.current
      const scene = new T.Scene()
      scene.background = new T.Color('#b5aa94')
      const camera = new T.PerspectiveCamera(68, 1, .1, 40)
      renderer = new T.WebGLRenderer({ antialias: true })
      renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
      root.appendChild(renderer.domElement)
      scene.add(new T.HemisphereLight(0xfff3d8, 0x414957, 2.8))
      const light = new T.DirectionalLight(0xffffff, 2.4)
      light.position.set(1, 4, 3); scene.add(light)
      function box(x,y,z,w,h,d,color) {
        const geometry = new T.BoxGeometry(w,h,d)
        const material = new T.MeshStandardMaterial({ color, roughness: .85 })
        const mesh = new T.Mesh(geometry,material)
        mesh.position.set(x,y,z); scene.add(mesh)
        resources.push(geometry,material)
      }
      box(0,-.08,0,7,.16,8,'#665041')
      box(0,1.6,-3,7,3.2,.12,'#c7bfaa')
      box(-3.4,1.6,0,.12,3.2,6,'#d2c9b6')
      box(3.4,1.6,0,.12,3.2,6,'#c6bfab')
      box(0,3.25,0,7,.1,8,'#e4ddce')
      // Bed, mattress, pillow and side cabinet mirror the broad room layout.
      box(1.4,.23,-1.1,2,.46,2.8,'#302c2b')
      box(1.4,.56,-1.1,2.08,.24,2.85,'#737b86')
      box(1.4,.74,-2.05,1.35,.18,.58,'#969eaa')
      box(-.55,.52,-2.2,.92,1.04,.68,'#262a2d')
      for (let j=0;j<2;j++) {
        box(-.55,.28+j*.46,-1.849,.8,.38,.035,'#353839')
        box(-.55,.3+j*.46,-1.82,.18,.025,.025,'#bca477')
      }
      for(let j=0;j<5;j++) box(-.36,1.08+j*.045,-2.2,.28,.04,.32,j%2?'#c3ac80':'#ded4be')
      // Door sits on the perpendicular left wall, beside the back-wall furniture.
      box(-3.29,1.15,-2.35,.1,2.3,1.0,'#585856')
      box(-3.20,1.15,-2.35,.1,2.16,.85,'#e1dfd5')
      // Window on the left wall, with frame, dark glass and horizontal blinds.
      box(-3.28,1.95,-.9,.12,1.35,1.55,'#eee9dd')
      box(-3.19,1.95,-.9,.06,1.17,1.37,'#7395ac')
      box(-3.12,1.95,-.9,.08,1.17,.045,'#e5e0d4')
      for (let j=0;j<8;j++) box(-3.11,1.43+j*.145,-.9,.055,.03,1.37,'#dad5c7')
      box(-3.10,1.25,-.9,.32,.06,1.68,'#eee9dd')
      const grid = new T.GridHelper(6,24,0x59caba,0x758b88)
      grid.position.y=.015; grid.material.transparent=true; grid.material.opacity=.22
      scene.add(grid); resources.push(grid.geometry,grid.material)
      const resize=()=>{ const w=root.clientWidth,h=root.clientHeight; renderer.setSize(w,h); camera.aspect=w/h; camera.updateProjectionMatrix() }
      observer=new ResizeObserver(resize); observer.observe(root); resize()
      const render=()=>{
        const t=timeRef.current
        const pose = demoPose(t)
        camera.position.set(pose.x, pose.y, pose.z)
        camera.lookAt(pose.x + Math.sin(pose.yaw) * 4, pose.y - .55, pose.z - Math.cos(pose.yaw) * 4)
        camera.updateMatrixWorld()
        // Keep the bed annotation attached to the furniture as perspective changes.
        if (boxRef.current) {
          const corners = []
          for (const x of [.36,2.44]) for (const y of [.44,.83]) for (const z of [-2.53,.33]) {
            const point = new T.Vector3(x,y,z)
            if (point.clone().applyMatrix4(camera.matrixWorldInverse).z < -.1) corners.push(point.project(camera))
          }
          const left = Math.max(0, Math.min(...corners.map(p => (p.x+1)*50)))
          const right = Math.min(100, Math.max(...corners.map(p => (p.x+1)*50)))
          const top = Math.max(0, Math.min(...corners.map(p => (1-p.y)*50)))
          const bottom = Math.min(100, Math.max(...corners.map(p => (1-p.y)*50)))
          Object.assign(boxRef.current.style, { display: t > 3 && right > left && bottom > top ? 'block' : 'none', left: `${left}%`, top: `${top}%`, width: `${right-left}%`, height: `${bottom-top}%` })
        }
        renderer.render(scene,camera)
        frame=requestAnimationFrame(render)
      }; render()
    })
    return ()=>{ disposed=true; cancelAnimationFrame(frame); observer?.disconnect(); resources.forEach(r=>r.dispose()); renderer?.dispose(); renderer?.domElement.remove() }
  },[])
  const t = timeRef.current
  const pose = demoPose(t)
  return <div className="demo-room">
    <div ref={rootRef} className="demo-room__scene" />
    <div className="demo-room__tag">SYNTHETIC CAMERA VIEW</div>
    <div className="demo-room__reticle">+</div>
    <div ref={boxRef} className="demo-room__box" style={{ display: 'none' }}><span>BED · SIMULATED POI</span></div>
    <div className="demo-room__decision"><span>NAVIGATION SIMULATION</span><strong>{pose.stage}</strong><small>Yaw {Math.round(pose.yaw * 180 / Math.PI)}° · Forward room scan · Room 01</small></div>
  </div>
}
