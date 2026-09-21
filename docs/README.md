# Documentation

Start with the [project overview](../README.md) for the demo, quickstart, and validation boundaries.

## Understand the system

- [Architecture](architecture.md): why the harness owns the hardware boundary and video fanout.
- [Perception pipeline](rafa-vlm-pipeline.md): process contracts, model setup, and fallback behavior.
- [Control boundary](llm-control-boundary.md): the separation between model intent and executable motion.
- [Spatial context](spatial-vlm-context.md): the intended relationship between observations, memory, and navigation.

## Run and inspect

- [Hardware runbook](hardware-runbook.md): simulator-first setup and Tello operation.
- [Offline debugging](offline-debug-logging.md): saved observations, decisions, and flight reports.
- [Demo reproduction](../demo/README.md): isolated frontend simulation and video export.

## Evidence and experiments

- [Recorded model benchmarks](rafa-benchmark-results.md): local latency measurements and runtime tradeoffs.
- [Model options](rafa-model-options.md): candidate selection and experimental alternatives.
- [Reconstruction plan](three-d-reconstruction-plan.md): staged mapping work, including capabilities still pending.

## Historical design material

These describe planning or earlier development states, not current acceptance results:

- [Original hackathon README](archive/hackathon-readme.md)
- [Hackathon workplan](../WORKPLAN.md) and [interface agreement](../CONSTITUTION.md)
- [Frontend design](frontend-redesign-spec.md) and [3D viewer design](3d-viewer-spec.md)
- [Foundry models](foundry-models.md) and [Palantir setup](palantir-ontology-setup.md)
