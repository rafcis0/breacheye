# Frontend Redesign Spec: Palantir-Grade Tactical COP

**Status:** Approved for implementation
**Date:** 2026-05-03
**Source:** War room a7af9f13 (Liara + Kelly + Garrus)

## Design Vision

Take BreachEye from AI-scaffolded prototype to production-grade tactical COP.
Palantir's design *language* (colors, density, typography) delivered through
shadcn/ui + Tailwind CSS v4 (lightweight, accessible, owned by us).

**What makes it "feel Palantir":**
1. Dark, cool-toned backgrounds with subtle blue undertone (Slate, not pure black)
2. High information density with compact spacing (4px grid)
3. Monochrome accent strategy — one primary blue, semantic status colors, nothing else
4. Inter + JetBrains Mono typography pairing
5. Glassmorphism panels floating over rich content (video/map)
6. Restrained elevation — white borders on dark (not box-shadow)
7. Data-first layout — every pixel earns its place
8. Defense-standard status colors (Astro UXDS)
9. Mission-phase-aware layout adaptation

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Component library | shadcn/ui (copy-paste, Radix primitives) | 5-20KB, full control, own every line |
| CSS framework | Tailwind CSS v4 | OKLCH tokens, coexists with existing CSS |
| Color system | Blueprint dark palette + Astro UXDS status | Professional + defense-grade |
| Typography | Inter (UI) + JetBrains Mono (data) | Matched x-height, max readability |
| Layout | shadcn Resizable + CSS Grid | Phase-aware panel management |

## Design Tokens

### Backgrounds (Tailwind Slate, cool blue undertone)

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-deepest` | `#020617` (slate-950) | Full-bleed canvas behind video/map |
| `--bg-app` | `#0f172a` (slate-900) | Application chrome |
| `--bg-surface` | `#1e293b` (slate-800) | Elevated panels, cards |
| `--bg-elevated` | `#334155` (slate-700) | Hover states, active surfaces |
| `--bg-glass` | `rgba(17,25,40,0.75)` | Glassmorphism overlay panels |

### Text

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#F6F7F9` | Primary text |
| `--text-secondary` | `#94a3b8` (slate-400) | Secondary labels |
| `--text-muted` | `#64748b` (slate-500) | Disabled, placeholder |
| `--text-subtle` | `#475569` (slate-600) | Timestamps, metadata |

### Accent (Blueprint intent system)

| Token | Value | Usage |
|-------|-------|-------|
| `--accent-primary` | `#2D72D2` (Blueprint blue3) | Primary actions, active states |
| `--accent-primary-light` | `#8ABBFF` (Blueprint blue5) | Links, highlights on dark |
| `--accent-success` | `#238551` (Blueprint green3) | Connected, confirmed |
| `--accent-warning` | `#C87619` (Blueprint orange3) | Caution indicators |
| `--accent-danger` | `#CD4246` (Blueprint red3) | Errors, destructive |

### Status (Astro UXDS defense standard)

| Level | Color | Shape | Usage |
|-------|-------|-------|-------|
| Critical | `#FF3838` | Triangle | Emergency, motor kill |
| Serious | `#FFB302` | Diamond | Low battery, connection lost |
| Caution | `#FCE83A` | Rectangle | Warning, degraded |
| Normal | `#56F000` | Circle | Healthy, connected |
| Standby | `#2DCCFF` | Square | Ready, available |
| Off | `#A4ABB6` | X | Disabled, unavailable |

Colors MUST pair with shapes for colorblind accessibility.

### Borders

| Token | Value | Usage |
|-------|-------|-------|
| `--border-default` | `rgba(255,255,255,0.08)` | Panel borders |
| `--border-subtle` | `rgba(255,255,255,0.05)` | Subtle separation |
| `--border-strong` | `rgba(255,255,255,0.15)` | Active/focused |
| `--border-glass` | `rgba(255,255,255,0.1)` | Glassmorphism edge |

### Typography Scale

| Level | Size | Weight | Font | Usage |
|-------|------|--------|------|-------|
| Display | 28px | 600 | Inter | Mission phase header |
| H1 | 22px | 600 | Inter | Panel titles |
| H2 | 18px | 500 | Inter | Section headers |
| Body | 14px | 400 | Inter | Default text |
| Small | 12px | 400 | Inter | Labels, metadata |
| Tiny | 11px | 500 | Inter | Status bar (uppercase) |
| Data value | 13px | 500 | JetBrains Mono | Telemetry values |
| Data label | 11px | 600 | Inter | Telemetry labels (uppercase) |

### Spacing (4px base grid)

| Token | Value | Compact | Comfortable |
|-------|-------|---------|-------------|
| `--space-1` | 4px | Icon-to-text | Icon-to-text |
| `--space-2` | 8px | Internal padding | - |
| `--space-3` | 12px | - | Internal padding |
| `--space-4` | 16px | Panel padding | - |
| `--space-6` | 24px | - | Panel padding |

Compact mode during active flight. Comfortable mode during pre/post-flight.

### Glassmorphism Panel

```css
.panel-glass {
  background: rgba(17, 25, 40, 0.75);
  backdrop-filter: blur(12px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.36);
  border-radius: 8px;
}

/* Tailwind equivalent */
/* bg-slate-900/75 backdrop-blur-xl border border-white/10
   shadow-[0_8px_32px_0_rgba(0,0,0,0.36)] rounded-lg */
```

## Layout Architecture

### Three-Zone Layout (replaces sidebar scroll model)

**Zone A** — Primary canvas (video or 3D), `flex: 1`
**Zone B** — Right panel, fixed 320px, no scroll
**Zone C** — Bottom status bar, 32px fixed

```
┌─────────────────────────────────────────────────────────────────────┐
│  BREACHEYE  [ACTIVE]    BAT:100%  ALT:85cm  T:04:32   ● CONNECTED  │  48px header
├──────────────────────────────────────┬──────────────────────────────┤
│                                      │  [LAND]    [EMERGENCY]       │
│                                      ├──────────────────────────────┤
│  ZONE A: PRIMARY CANVAS             │                              │
│  (video + detection overlay)         │  TACTICAL MAP                │
│  Full-bleed, no chrome               │  (fills remaining space)     │
│                                      │                              │
│                                      │                              │
├──────────────────────────────────────┴──────────────────────────────┤
│  LINK:● OK  MODE:AIRBORNE  POI:12  HOT:2  WS:LIVE  [3D VIEW]      │  32px bottom bar
└─────────────────────────────────────────────────────────────────────┘
```

### Mission-Phase Adaptation

#### Pre-Flight (drone grounded)

- Zone A: Camera preview (static or live)
- Zone B: Preflight checklist (connection, battery, feed) + LAUNCH MISSION CTA
- No EMERGENCY button. No detection overlay.
- Bottom bar: system status only

#### Active Flight (drone airborne)

- Zone A: Live video + detection overlay (full attention)
- Zone B top: LAND + EMERGENCY (fixed ~100px)
- Zone B bottom: Tactical map (fills remaining space)
- Header: compact telemetry chips (BAT, ALT, TIME)
- Bottom bar: LINK, MODE, POI count, WS status, [3D VIEW] toggle

#### Post-Flight (drone landed)

- Zone A: 3D reconstruction (promoted to primary, full orbit controls)
- Zone B: Tactical map (POI review mode) + POI list + EXPORT/REPLAY CTAs
- No EMERGENCY button. No flight controls.
- Header: mission summary (total time, POI count)

## Component Changes

### VideoPanel
- Remove `/api/video.mjpeg` from footer
- Rewrite no-signal text: "Check drone WiFi" (not port numbers)
- Add detection count badge to header
- Add frame age indicator (confirms feed is fresh)

### FlightControls
- EMERGENCY: hold-to-activate (500ms) with visual progress ring
- EMERGENCY: independent state — never locked by LAND busy
- Post-command: 3s full-width status banner
- Phase-aware: absent in pre-flight and post-flight

### TelemetryHUD
- Dissolve into global header as compact chips
- BAT, ALT, TIME always visible in header bar
- "WS"/"POLL" → "LIVE"/"DELAYED" with color
- Battery warning glow at <20%

### TacticalMap
- Add legend (colored dots + category labels) in canvas corner
- Add POI count to header: "TACTICAL MAP · 12 POI"
- Add compass/north indicator
- Remove crosshair cursor (nothing is clickable)

### Map3D
- Add Three.js OrbitControls for operator review
- Show point count in header: "3D RECON · 4,823 pts"
- Phase-aware: on-demand toggle during flight, primary view post-flight
- Remove auto-rotate (operationally useless)

### DetectionOverlay
- Swap label priority: human label first, category code small
- Make threat badge larger (12px min)
- Add detection count to parent video header

### New: Shared WebSocket Context
- Consolidate 3 separate WS connections into one shared hook/context
- Global connection health indicator
- Single reconnect with backoff

## What to Avoid

1. Pure black backgrounds (#000) — causes eye strain, no depth
2. Multiple accent colors competing — one primary, the rest semantic
3. Decorative animations — only animate status changes
4. Equal visual weight across all panels — hierarchy must be immediate
5. Developer-facing information in operator views
6. Large padding during active operations
7. Box shadows alone for dark elevation — use inset borders

## Migration Path

1. **Foundation (30-45 min):** Tailwind v4 + shadcn/ui init + design tokens
2. **Layout (45-60 min):** Three-zone with ResizablePanelGroup
3. **Glassmorphism (30 min):** Panel system
4. **Header + bottom bar (30 min):** Compact telemetry, status indicators
5. **Safety (30 min):** Hold-to-activate EMERGENCY
6. **Mission phases (45 min):** Pre/active/post-flight adaptation
7. **Polish (ongoing):** Per-component improvements

## References

| Source | URL |
|--------|-----|
| Blueprint.js Colors | github.com/palantir/blueprint/.../colors.ts |
| Astro UXDS Status System | astrouxds.com/patterns/status-system/ |
| shadcn/ui Theming | ui.shadcn.com/docs/theming |
| Linear Redesign | linear.app/now/how-we-redesigned-the-linear-ui |
| QGroundControl | docs.qgroundcontrol.com |
| ATAK Design System | figma.com/community/file/1571370238280853168 |
