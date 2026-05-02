# Palantir Ontology Setup — BreachEye

Hackathon-pace guide. Copy-paste actionable. Time budget: 3h total, cut at H+8 if not live.

---

## 1. Prerequisites

**Environment variables — set before anything else:**

```bash
export FOUNDRY_HOST="https://<your-foundry-hostname>"
export FOUNDRY_TOKEN="<your-bearer-token>"
```

**Python SDK:**

```bash
pip install foundry-platform-sdk
# or if using uv:
uv pip install foundry-platform-sdk
```

**Verify connectivity:**

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $FOUNDRY_TOKEN" \
  "$FOUNDRY_HOST/api/v2/ontologies"
# Expect 200
```

---

## 2. Create TacticalPoi Object Type

In **Ontology Manager UI** (`$FOUNDRY_HOST/ontology-manager`):

1. Click **New Object Type** → name: `TacticalPoi`
2. Add properties in order:

| Property | Foundry Type | Notes |
|----------|-------------|-------|
| `poiId` | String | Set as **Primary Key** |
| `scanId` | String | |
| `category` | String | T1-01 through ROOM |
| `label` | String | Human-readable description |
| `confidence` | Double | Range 0.0–1.0 |
| `posX` | Double | X coord, meters, local frame |
| `posY` | Double | Y coord, meters, local frame |
| `posZ` | Double | Z coord, meters, local frame |
| `floor` | Integer | 0 = ground floor |
| `threatLevel` | String | HOT/WARM/CAUTION/CLEAR/INFO |
| `createdAt` | Timestamp | ISO 8601 |

3. Set `poiId` as **Primary Key** (click the key icon on that property row).
4. **Note:** Foundry has no native 3D point type — use three separate Doubles (`posX`, `posY`, `posZ`).
5. Click **Save** → **Publish**.

---

## 3. Create FlightDecision Object Type

1. Click **New Object Type** → name: `FlightDecision`
2. Add properties:

| Property | Foundry Type | Notes |
|----------|-------------|-------|
| `decisionId` | String | Set as **Primary Key** |
| `scanId` | String | FK — links to parent scan |
| `timestamp` | Timestamp | When decision was made |
| `fromState` | String | State machine prior state |
| `toState` | String | State machine next state |
| `action` | String | move_forward, rotate_left, etc. |
| `confidence` | Double | VLM confidence 0.0–1.0 |
| `reasoning` | String | VLM explanation string |
| `batteryPercent` | Integer | Tello battery at decision time |

3. Set `decisionId` as **Primary Key**.
4. Click **Save** → **Publish**.

---

## 4. Create Action Types

### Action: `create-tactical-poi`

1. In Ontology Manager → **Actions** → **New Action Type**
2. Name: `create-tactical-poi`
3. Add parameters (one per property, matching names exactly):

| Parameter | Type | Maps to |
|-----------|------|---------|
| `poiId` | String | TacticalPoi.poiId (PK) |
| `scanId` | String | TacticalPoi.scanId |
| `category` | String | TacticalPoi.category |
| `label` | String | TacticalPoi.label |
| `confidence` | Double | TacticalPoi.confidence |
| `posX` | Double | TacticalPoi.posX |
| `posY` | Double | TacticalPoi.posY |
| `posZ` | Double | TacticalPoi.posZ |
| `floor` | Integer | TacticalPoi.floor |
| `threatLevel` | String | TacticalPoi.threatLevel |
| `createdAt` | Timestamp | TacticalPoi.createdAt |

4. Logic: **Create Object** → select `TacticalPoi` → map each parameter to its property.
5. Click **Save** → **Publish**.

### Action: `log-flight-decision`

1. **New Action Type** → name: `log-flight-decision`
2. Parameters:

| Parameter | Type | Maps to |
|-----------|------|---------|
| `decisionId` | String | FlightDecision.decisionId (PK) |
| `scanId` | String | FlightDecision.scanId |
| `timestamp` | Timestamp | FlightDecision.timestamp |
| `fromState` | String | FlightDecision.fromState |
| `toState` | String | FlightDecision.toState |
| `action` | String | FlightDecision.action |
| `confidence` | Double | FlightDecision.confidence |
| `reasoning` | String | FlightDecision.reasoning |
| `batteryPercent` | Integer | FlightDecision.batteryPercent |

3. Logic: **Create Object** → select `FlightDecision` → map each parameter.
4. Click **Save** → **Publish**.

---

## 5. Upload Sample Data

1. In Foundry **Data Connection** or **Datasets** → **Upload File**
2. Upload `demo/sample_pois.csv` → name dataset `breacheye_sample_pois`
3. Upload `demo/sample_decisions.csv` → name dataset `breacheye_sample_decisions`
4. For each dataset → **Sync to Ontology**:
   - `breacheye_sample_pois` → object type `TacticalPoi`, primary key column `poiId`
   - `breacheye_sample_decisions` → object type `FlightDecision`, primary key column `decisionId`
5. Trigger sync → verify row counts match CSV.

---

## 6. Verify

**Query TacticalPoi objects back:**

```bash
curl -s \
  -H "Authorization: Bearer $FOUNDRY_TOKEN" \
  "$FOUNDRY_HOST/api/v2/ontologies/palantir/objects/TacticalPoi?pageSize=5" \
  | python3 -m json.tool
```

**Query FlightDecision objects:**

```bash
curl -s \
  -H "Authorization: Bearer $FOUNDRY_TOKEN" \
  "$FOUNDRY_HOST/api/v2/ontologies/palantir/objects/FlightDecision?pageSize=5" \
  | python3 -m json.tool
```

**Test single create-tactical-poi action:**

```bash
curl -s -X POST \
  -H "Authorization: Bearer $FOUNDRY_TOKEN" \
  -H "Content-Type: application/json" \
  "$FOUNDRY_HOST/api/v2/ontologies/palantir/actions/create-tactical-poi/apply" \
  -d '{
    "parameters": {
      "poiId": "T1-01-999",
      "scanId": "scan-verify-001",
      "category": "T1-01",
      "label": "Test Entry Point",
      "confidence": 0.9,
      "posX": 1.0,
      "posY": 1.0,
      "posZ": 0.0,
      "floor": 0,
      "threatLevel": "INFO",
      "createdAt": "2026-05-02T14:00:00Z"
    }
  }'
# Expect {"edits": {...}}
```

---

## 7. Workshop Dashboard

Build in **Workshop** (`$FOUNDRY_HOST/workspace/module-editor`):

- [ ] **Map widget** — 2D floor plan overlay, plot TacticalPoi by posX/posY, color by `category` or `threatLevel`
- [ ] **Object table** — TacticalPoi table, columns: poiId, label, category, threatLevel, confidence, floor
- [ ] **Metric cards** — POI count by threatLevel (HOT, WARM, CAUTION, CLEAR), battery gauge from latest FlightDecision
- [ ] **AIP chatbot** — Attach AIP Agent, give it access to TacticalPoi and FlightDecision object sets, prompt: "Tactical analyst for indoor drone ops"
- [ ] **Filter** — scanId dropdown to isolate active mission

Time budget: 45min for map + table, 30min for chatbot. Cut chatbot if behind.
