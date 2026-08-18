# Flat Plant API <!-- ci test -->

> **Live:** `https://flat-plants-api.azurewebsites.net`
> **Repo:** `https://github.com/KPaks1/flat-api`
> **Deploys:** automatically on push to `master` via GitHub Actions

Serverless Azure Functions API for a shared flat. Two things it does:

1. **NFC plant watering** — each plant has an NFC sticker. Scanning it marks the plant as watered and pushes a notification to all flatmates' browsers (no app required).
2. **Watering reminders** — a timer runs every 6 hours and sends push notifications when a plant is overdue for watering.

Stack: Python · Azure Functions (Consumption plan) · Azure Table Storage · Azure Storage Queue · Web Push (VAPID)

---

## Prerequisites

- Python 3.11+
- Node.js (for Azurite and Azure Functions Core Tools)
- Azure Functions Core Tools v4: `npm install -g azure-functions-core-tools@4`
- Azure CLI (for deployment): [install guide](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)

---

## Local development

### 1. Install

```bat
install.bat
```

This creates the virtual environment, installs dependencies, and generates VAPID keys into `local.settings.json`. Run it once. Safe to re-run — it skips steps already done.

### 2. Start

```bat
start.bat
```

Opens Azurite (local Azure Storage emulator) in a separate window, then starts the Functions runtime. Both windows need to stay open while developing.

### 3. Test

```
Subscribe page : http://localhost:7071/api/subscribe
Plants API     : http://localhost:7071/api/plants
```

For Web Push testing the subscribe page needs HTTPS. Use [ngrok](https://ngrok.com):

```bat
ngrok http 7071
```

Then open `https://<ngrok-url>/api/subscribe` in your browser.

---

## Flatmate onboarding

Each flatmate visits the subscribe URL once and clicks **Enable Notifications**. That's it — no app to install.

- **Production:** `https://<your-function-app>.azurewebsites.net/api/subscribe`
- **Local (via ngrok):** `https://<ngrok-url>/api/subscribe`

> **iOS note:** iOS 16.4–16.x requires adding the page to your Home Screen before subscribing. iOS 17+ works directly in Safari.

---

## NFC sticker setup

Each plant gets its own sticker. To program one:

1. Install [NFC Tools](https://www.wakdev.com/en/apps/nfc-tools.html) (free, iOS & Android)
2. Write → Add a record → URL/URI
3. Enter: `https://<your-function-app>.azurewebsites.net/api/nfc/<plant-id>`
   - Example: `.../api/nfc/bedroom-monstera`
4. Tap Write and hold your phone to the sticker

When scanned, the phone browser opens and shows a confirmation page. No app needed.

---

## Managing plants

### Add a plant

```bash
curl -X POST https://<app>.azurewebsites.net/api/plants \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Monstera",
    "room": "Bedroom",
    "plant_type": "Monstera Deliciosa",
    "watering_interval_days": 3.5
  }'
```

`watering_interval_days` examples: `3.5` = twice a week, `7` = once a week, `14` = fortnightly.

The `plant_id` is auto-generated from room + name (e.g. `bedroom-monstera`). Use it in the NFC sticker URL and for updates/deletes.

### List plants

```bash
curl https://<app>.azurewebsites.net/api/plants
```

### Update a plant

```bash
curl -X PUT https://<app>.azurewebsites.net/api/plants/bedroom-monstera \
  -H "Content-Type: application/json" \
  -d '{"watering_interval_days": 4}'
```

### Delete a plant

```bash
curl -X DELETE https://<app>.azurewebsites.net/api/plants/bedroom-monstera
```

---

## API reference

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/nfc/{plant_id}` | Mark plant watered + notify flatmates |
| GET | `/api/plants` | List all plants |
| POST | `/api/plants` | Add a plant |
| PUT | `/api/plants/{plant_id}` | Update plant fields |
| DELETE | `/api/plants/{plant_id}` | Remove a plant |
| GET | `/api/subscribe` | Subscription page (serve to flatmates) |
| POST | `/api/subscribe` | Register a push subscription |
| GET | `/api/vapid-public-key` | VAPID public key (used by subscribe page) |

---

## Deploy to Azure

### 1. Create resources

```bash
RESOURCE_GROUP="flat-plants-rg"
LOCATION="uksouth"
STORAGE_ACCOUNT="flatplantsstore"   # must be globally unique, lowercase
FUNCTION_APP="flat-plants-api"       # must be globally unique

az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

az storage account create \
  --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" --sku Standard_LRS --kind StorageV2

az functionapp create \
  --name "$FUNCTION_APP" --resource-group "$RESOURCE_GROUP" \
  --storage-account "$STORAGE_ACCOUNT" \
  --consumption-plan-location "$LOCATION" \
  --runtime python --runtime-version 3.11 \
  --functions-version 4 --os-type Linux

STORAGE_CONN=$(az storage account show-connection-string \
  --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
  --query connectionString --output tsv)
```

### 2. Set application settings

When you ran `install.bat`, it printed your VAPID keys. Use those values here:

```bash
az functionapp config appsettings set \
  --name "$FUNCTION_APP" --resource-group "$RESOURCE_GROUP" \
  --settings \
    "STORAGE_CONNECTION_STRING=$STORAGE_CONN" \
    "VAPID_PUBLIC_KEY=<from install.bat output>" \
    "VAPID_PRIVATE_KEY=<from install.bat output>" \
    "VAPID_CLAIMS_EMAIL=<your email>"

az functionapp cors add \
  --name "$FUNCTION_APP" --resource-group "$RESOURCE_GROUP" \
  --allowed-origins "*"
```

### 3. Deploy

```bash
call .venv\Scripts\activate.bat
func azure functionapp publish flat-plants-api --python
```

### Estimated cost

| Resource | Monthly cost |
|----------|-------------|
| Azure Functions (Consumption) | Free (1M executions included) |
| Azure Table Storage | ~$0.01 |
| Azure Storage Queue | ~$0.00 |
| **Total** | **~$0.02** |

---

## Todo

- [ ] **Fix production startup** — functions returning 404 in production; Oryx build settings (`ENABLE_ORYX_BUILD`, `SCM_DO_BUILD_DURING_DEPLOYMENT`) added, redeployment in progress
- [ ] **Program NFC stickers** — one per plant, URL format: `https://flat-plants-api.azurewebsites.net/api/nfc/<plant-id>`
- [ ] **Add plants** — use `requests.http` in VS Code or curl to POST to `/api/plants`
- [ ] **Onboard flatmates** — share `https://flat-plants-api.azurewebsites.net/api/subscribe` (note: subscribe whitelist set to `REDACTED_IP`)
- [ ] **Watering token** — add a shared secret to the NFC URL (`?token=xxx`) to prevent anyone with the URL from triggering waterings
- [ ] **Who watered tracking** — per-device tokens so notifications say which flatmate watered the plant

---

## Project structure

```
flat-api/
├── function_app.py          # All Azure Functions
├── host.json                # Functions host config
├── local.settings.json      # Local dev config (gitignored)
├── requirements.txt
├── install.bat              # One-time dev setup
├── start.bat                # Start local dev server
├── setup_keys.py            # VAPID key generation (called by install.bat)
├── lib/
│   ├── storage.py           # Azure Table Storage + Queue helpers
│   └── webpush.py           # Web Push notification sender
└── static/
    ├── subscribe.html       # Flatmate subscription page
    └── sw.js                # Service worker
```
