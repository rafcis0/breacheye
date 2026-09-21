# Frontend demonstration

[Watch the finished video](assets/breacheye-demo.mp4) · [Back to the project](../README.md)

The curated video and preview in `assets/` are included in Git; raw recordings and intermediate captures remain local.

Open `http://127.0.0.1:5173/?demo=1` after starting `npm run dev` in
`frontend/`. This runs the real interface with a synthetic bedroom camera,
flight telemetry, example points of interest, and gradually accumulated room
geometry. The simulation is explicit and isolated: it opens no hardware
WebSocket, requests no hardware API, and its flight controls send no commands.

The room and telemetry illustrate the rise, traverse toward the bed, and wall approach in the phone footage.
They are not reconstructed from that footage and are not model measurements.
The original clip is preserved in the left panel of the exported video,
including its audio. The right panel is the rendered frontend simulation.

To reproduce the combined MP4, install frontend dependencies, run
`npx playwright install chromium` in `frontend/`, and leave Vite running. From
the repository root:

```sh
uv run --with imageio-ffmpeg python scripts/render_demo_video.py /path/to/clip.MOV
```

The output is `demo/generated/breacheye-side-by-side.mp4`. Generated videos
and frames stay local and are ignored by Git. `--output` chooses another path;
`--reuse-frames` recomposes an existing capture. `DEMO_BROWSER` can select an
existing Chromium executable and `DEMO_FONT` a local TrueType font (the default
is macOS Arial). Use `DEMO_URL` when Vite runs on a different local port.

Capture checks the rendered layout, scene, mission sequence, browser errors,
and hardware isolation, including activation of a simulated flight control.
The capture clock advances at 30 fps independent of screenshot speed.
