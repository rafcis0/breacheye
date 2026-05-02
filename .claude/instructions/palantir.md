# Palantir AIP Integration

Timebox: 3 hours max. Cut if not working by H+8.

## What We're Building

- Push TacticalPoi + FlightDecision objects to Foundry Ontology
- Workshop COP dashboard: 2D map + POI table + AIP chatbot
- Batch push every 5 seconds from the state machine

## Authentication

```bash
# Bearer token — get from Foundry Settings > Tokens
export FOUNDRY_TOKEN="<token from hackathon setup>"
export FOUNDRY_HOST="https://<hackathon-instance>.palantirfoundry.com"
```

All API calls use: `Authorization: Bearer $FOUNDRY_TOKEN`

## Ontology Schema

### TacticalPoi (primary object)

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| poiId | String | PK | Format: T1-01-001 |
| scanId | String | Yes | Links to parent scan |
| category | String | Yes | T1-01 through ROOM (see CONSTITUTION) |
| label | String | Yes | Human-readable |
| confidence | Double | Yes | 0.0-1.0 |
| posX | Double | Yes | 3D x coordinate (meters, local frame) |
| posY | Double | Yes | 3D y coordinate |
| posZ | Double | Yes | 3D z coordinate |
| floor | Integer | Yes | 0 = ground |
| threatLevel | String | Yes | HOT/WARM/CAUTION/CLEAR/INFO |
| createdAt | Timestamp | No | ISO 8601 |

No native 3D point type in Foundry. Store as three Doubles.
GeoPoint (lat/lon) only if we geo-reference the building.

### FlightDecision (stretch)

| Property | Type | Notes |
|----------|------|-------|
| decisionId | String | PK, UUID |
| scanId | String | FK |
| timestamp | Timestamp | When decided |
| fromState | String | State machine state |
| toState | String | New state |
| action | String | move_forward, rotate_left, etc. |
| confidence | Double | VLM confidence |
| reasoning | String | VLM explanation |
| batteryPercent | Integer | Tello battery at decision time |

## Fastest Data Path: CSV Upload (30 min)

1. Flatten POI JSON to CSV:
```python
import csv
def poi_to_csv(pois, scan_id, output_path):
    with open(output_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'poi_id','scan_id','category','label','confidence',
            'pos_x','pos_y','pos_z','floor','threat_level','created_at'
        ])
        w.writeheader()
        for p in pois:
            w.writerow({
                'poi_id': p['id'], 'scan_id': scan_id,
                'category': p['category'], 'label': p['label'],
                'confidence': p['confidence'],
                'pos_x': p.get('pos_x', 0), 'pos_y': p.get('pos_y', 0),
                'pos_z': p.get('pos_z', 0),
                'floor': p.get('floor', 0),
                'threat_level': p.get('threat_level', 'CLEAR'),
                'created_at': p.get('created_at', '')
            })
```

2. Drag CSV into Foundry UI > New Dataset
3. Create object type `TacticalPoi` in Ontology Manager, map properties
4. Publish

## Live Push Path: REST API Actions

Objects are created via Actions, not direct POST.

```bash
# Create single POI
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FOUNDRY_TOKEN" \
  "$FOUNDRY_HOST/api/v2/ontologies/palantir/actions/create-tactical-poi/apply" \
  -d '{
    "parameters": {
      "poiId": "T1-01-001",
      "scanId": "scan-001",
      "category": "T1-01",
      "label": "Entry Point",
      "confidence": 0.87,
      "posX": 3.42, "posY": 1.5, "posZ": -7.8,
      "floor": 1,
      "threatLevel": "CLEAR"
    }
  }'

# Batch create (multiple POIs at once)
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FOUNDRY_TOKEN" \
  "$FOUNDRY_HOST/api/v2/ontologies/palantir/actions/create-tactical-poi/applyBatch" \
  -d '{
    "requests": [
      {"parameters": {"poiId": "T1-01-001", "category": "T1-01", ...}},
      {"parameters": {"poiId": "T2-03-001", "category": "T2-03", ...}}
    ]
  }'
```

Action types must be pre-configured in Ontology Manager. Ask Palantir staff on-site.

## Workshop COP Dashboard (60 min)

Build order:
1. Map widget — building location, POI markers colored by threat level
2. Object Table widget — filterable POI list (category, floor, threat)
3. Metric cards — total POIs, threat counts, battery, flight time
4. AIP Chatbot widget — "Show all chokepoints on floor 2"

### AIP Chatbot (20 min in Agent Studio)

1. Create chatbot in Agent Studio
2. Model: Claude 4 Sonnet or GPT-4.1, temperature 0
3. Retrieval context: TacticalPoi + FlightDecision objects
4. Object Query tool: all POI types, filter/aggregate/inspect
5. System prompt: "You are a tactical building analyst. Answer questions about detected POIs, threats, and room layouts using the Ontology data. Be concise and precise."
6. Publish, embed in Workshop as AIP Chatbot widget

### 3D Viewer (iframe)

Foundry has NO native 3D. Embed BabylonJS viewer as iframe:
- Install `@osdk/workshop-iframe-custom-widget` in viewer
- Bidirectional sync: Workshop variable changes -> viewer updates, viewer clicks -> Workshop variable
- CSP whitelist needed for viewer URL

## Python OSDK (alternative to REST)

```python
from foundry_platform_python import FoundryClient, UserTokenAuth
import os

auth = UserTokenAuth(
    hostname=os.environ["FOUNDRY_HOST"],
    token=os.environ["FOUNDRY_TOKEN"]
)
client = FoundryClient(auth=auth, hostname=os.environ["FOUNDRY_HOST"])

# Query POIs
pois = client.ontology.objects.TacticalPoi.where(
    TacticalPoi.category == "T1-01"
).iterate()
```

## Rate Limits

- 5,000 requests/min per user
- Batch actions preferred over individual creates
- Push accumulated POIs every 5 seconds, not per-detection

## If Palantir Isn't Working

The demo stands without it. The drone flies, the VLM detects, the tactical map renders. Palantir is the C2 layer on top. If access issues, API problems, or time pressure: cut it. Focus on the live demo.
