# Menu Catalog Generator — Build Plan

Internal admin tool. Menu photo in → reviewed, AI-generated dish catalog +
SmartBiz-ready Excel out. 3–4 concurrent internal users. Fully hosted, zero cost.

---

## 0. Decisions already locked

| Question | Decision |
|---|---|
| Runtime | Fully cloud. Nothing runs on anyone's PC. |
| Cost ceiling | Rs 0. No credit card on any service. |
| Usage shape | ~2–3 hrs/day, bursty. Idle-sleep is acceptable; mid-job death is not. |
| Frontend | React + Vite + TypeScript (not React Native for Web) |
| Excel target | SmartBiz bulk upload template v5 (= the Amazon seller sheet) |
| Low-confidence preview | Text concept card. No image spent before approval. |
| Gemini key | Per user, entered after login, encrypted at rest, revocable |
| ImgBB key | Per shop, entered in setup |

---

## 1. The stack (and why each piece is free)

> **Revised after verifying the free tiers rather than trusting memory.**
> Two assumptions failed, and both would have wasted a build:
> - **Hugging Face Docker Spaces are no longer free.** The docs now read:
>   *"Gradio and Docker Spaces run on compute and require a paid plan to
>   create: PRO for personal accounts."* Only **static** Spaces are free. HF is out.
> - **Render's free tier has no background workers at all**, spins down after
>   **15 min** of no inbound traffic, has no persistent disk, and its
>   credit-card policy is reported inconsistently by region.
>
> Conclusion: **no free host will reliably run an hour-long background
> worker.** So we stop needing one. See §1.2.

### 1.1 Services

| Layer | Service | Free tier | Card? | Why |
|---|---|---|---|---|
| DB | **Supabase Postgres** | 500 MB; pauses only after **7 days** idle | **No** | Verified. Daily use means it never pauses. |
| Image bytes | **Supabase Storage** | 1 GB (~3,000 dish images) | **No** | Cloudflare R2 is 10 GB but **requires a card**. Disqualified. |
| Public image URLs | **ImgBB** | unlimited, per-shop key | **No** | Already proven in the current tool; the sheet needs a fetchable URL. |
| API + SPA | **any free container host** | — | varies | Deliberately interchangeable — see §1.2. Ranked: Render free → Koyeb → Northflank → Cloud Run. |

### 1.2 The architectural change: the browser is the pacer

A free host will suspend a background thread. Fighting that is a losing game,
so generation is restructured to need no background thread at all.

**Old shape** (current tool): one process loops for an hour, sleeping between
Gemini calls. Dies the moment the host idles out.

**New shape:** the server only ever generates **one image per HTTP request**.

```
BROWSER                              SERVER                         DB
   |                                    |                            |
   |-- POST /api/jobs/{id}/step ------->|                            |
   |                                    |-- claim 1 queued item ---->|  UPDATE..
   |                                    |<-- item -------------------|  SKIP LOCKED
   |                                    |                            |
   |                                    |-- one Gemini image call    |
   |                                    |-- save bytes to Storage -->|
   |                                    |-- commit item as done ---->|
   |<-- {done, next_delay_ms, remaining}-|                            |
   |                                    |                            |
   |   sleep(next_delay_ms)  <- the PACE lives in the browser now    |
   |                                    |                            |
   |-- POST .../step ------------------>|   ... repeat until remaining == 0
```

Why this is strictly better here, not just a workaround:

| | Benefit |
|---|---|
| **Idle-sleep becomes impossible** | A request every ~30 s *is* the keep-alive. The host cannot idle out mid-run by construction. |
| **No background worker needed** | Which is exactly what Render's free tier forbids. |
| **Every request is short** | ~10–30 s, inside every free host's request timeout. A 429 returns instantly with `retry_after_ms` instead of sleeping server-side. |
| **Resume is free** | State was already per-item in the DB. Close the tab → the loop stops. Reopen → it continues. No image is ever regenerated. |
| **Free parallelism** | `SELECT … FOR UPDATE SKIP LOCKED` means two users, or two tabs, safely pull different items. |
| **Host-agnostic** | The backend is now an ordinary short-request web app. Render, Koyeb, Northflank, Cloud Run, or a paid host later — all work unchanged. |

The one real cost: **the tab must stay open while generating.** Given ~2–3 hrs
of active daily use and perfect resume, that is the right trade. The UI states
it plainly ("keep this tab open — closing it pauses, nothing is lost").

The adaptive pacing logic is **not** discarded — it moves from process memory
into a `pace_state` row keyed by `api_key_hash`, so the ×1.5-on-429 /
×0.92-on-success behaviour survives across requests, restarts, and hosts, and
stays independent per user key.

**Hard design rule: the backend is a plain Docker container, every secret in
an env var, no host-specific SDK.** Changing host is a redeploy, never a rewrite.

---

## 2. What we keep from the existing Python tool

The current engine is good and **the retry/pacing code is not to be rewritten
by anyone.** Ported as-is, only re-homed:

| Existing | Becomes | Change |
|---|---|---|
| `main.py` `_pace` / `_on_rate_limit` / `_on_success` | `engine/pacer.py` | Same maths, but state moves from process memory to a DB row keyed by `api_key_hash` — one pacer **per API key**, surviving restarts and host swaps. This is what makes 3–4 users independent. |
| `main.py` `_is_rate_limit` / `_is_auth_error` / `_extract_image_bytes` / `_finish_reason` | `engine/gemini.py` | verbatim |
| `main.py` `_fallback_prompt` ladder | `engine/prompt.py` | verbatim, kept as the safety net |
| `extract_menu.py` `RESPONSE_SCHEMA`, `EXTRACT_PROMPT`, `normalise_items`, `merge` | `engine/extract.py` | verbatim; cache key moves from JSON file to DB `sha256` |
| `imgbb.py` incl. `ImgbbUploadCap` | `engine/imgbb.py` | cache moves to DB |
| `smartbiz_export.py` | `engine/export.py` | template-copy approach kept (preserves all 29 validations); category mapping upgraded — see §7 |
| `progress.json` / `uploads.json` | Postgres tables | — |

**Deleted:** single-instance lock file, Drive uploader, CLI banners, `run_all.py`,
and the in-process `ThreadPoolExecutor` loop (replaced by the step endpoint, §1.2).

---

## 3. Database schema (Postgres)

```
users          id, username UNIQUE, password_hash, gemini_key_enc,
               gemini_key_hint, created_at, last_login_at

shops          id, name, created_by -> users, created_at, archived_at,
               brand_archetype, cuisine, price_tier, plating_style,
               lighting_mood, background_setting, prop_density, notes,
               style_profile JSONB,          -- derived once from reference
               reference_image_id -> images,
               imgbb_key_enc,
               business_category DEFAULT 'FOOD_AND_GROCERY',
               status

menu_uploads   id, shop_id, storage_key, filename, sha256,
               raw_json JSONB, extracted_at, is_menu, error
               UNIQUE (shop_id, sha256)

items          id, shop_id, position, name, category, price, description,
               source_menu,
               confidence INT, confidence_reason, concept_text,
               suggested_vessel, suggested_props JSONB,
               product_category,             -- one of the 15 valid strings
               status,                       -- see state machine below
               manual_ref_image_id -> images,
               prompt_used TEXT, attempts INT, last_error,
               image_id -> images, imgbb_url,
               price_conflict BOOL, edited_by, updated_at
               UNIQUE (shop_id, name, category)

images         id, shop_id, item_id, kind, storage_key, sha256,
               bytes_len, width, height, created_at

jobs           id, shop_id, kind, status, total, done, failed,
               started_at, finished_at, error, created_by, api_key_hash

job_events     id, job_id, ts, level, item_id, message   -- streams to UI

exports        id, shop_id, storage_key, filename, row_count,
               included_without_image INT, created_at, created_by
```

### Item state machine

```
              extract            classify
   (none) ---------------> new ------------+-----> approved ---+
                                           |                   |
                        confidence >= 90 --+                   |
                                           |                   v
                        confidence <  90 --+--> needs_review  queued
                                                 |   |          |
                             admin approves -----+   |          v
                                                     |      generating
                             admin holds ------------+          |
                                   |               +------------+-----------+
                                   v               v                        v
                             awaiting_ref      generated                 failed
                                   |               |                        |
                      ref uploaded +--> approved   v              retry ----+
                                                 hosted
```

Every transition records the acting user id. Nothing is destructive — a
regenerate keeps the prior image row.

---

## 4. Shop context — the 7 metrics

Collected on the setup screen, fed verbatim into every prompt.

| Field | Control | Example (Ghiza Chicken) | Example (Soya Chaap Corner) |
|---|---|---|---|
| `brand_archetype` | select | QSR chain (KFC-style) | Local neighbourhood eatery |
| `cuisine` | select + free text | Fried chicken / American QSR | North Indian street food |
| `price_tier` | select | Premium | Budget |
| `plating_style` | select | Clean, minimal, branded packaging | Rustic, generous, homestyle |
| `lighting_mood` | select | Bright, punchy, high-contrast | Warm, natural, soft |
| `background_setting` | select | Seamless studio backdrop | Textured rustic surface |
| `prop_density` | slider 0–3 | 1 (sparse) | 2 (moderate) |
| `notes` | textarea | "Never show cutlery" | — |

These are not decoration — §5 shows exactly where each lands in the prompt.

---

## 5. Prompt architecture — the core redesign

**The problem with the current prompt** (`main.py:494`): the style is hardcoded
English — *"the solid pale green background"*, *"do NOT copy the copper
kadhai"*. That text describes one specific reference photo. Upload a different
reference and the prompt now lies to the model.

**The fix: four independent layers, composed per item.**

```
LAYER 1  STYLE   derived ONCE per shop, cached in shops.style_profile
   A gemini-2.5-flash vision call reads the uploaded reference image and
   returns JSON: camera_angle, lighting, surface, background, colour_palette,
   mood, and - critically - vessel_in_reference + props_in_reference.
   Cost: one call per shop, ever.

LAYER 2  SHOP CONTEXT   the 7 metrics from §4, rendered to a sentence

LAYER 3  DISH   per item, from the classify call in §6
   name . category . description . suggested_vessel . suggested_props

LAYER 4  ANTI-REPETITION   computed, not AI
   - "Do not reproduce {style_profile.vessel_in_reference}"   <- dynamic now
   - "Do not reproduce {style_profile.props_in_reference}"
   - vessel comes from the dish, never from the reference
   - prop blocklist: no raw/uncooked form of the dish's own hero ingredient
     (no raw paneer blocks behind Paneer Masala) - but fruit behind a fruit
     shake IS allowed, because it is the literal input to that drink
   - a per-item rotation seed varies angle +/-5 deg and prop placement so
     100 images don't look stamped
```

### Vessel rule

AI suggests; a deterministic table validates and overrides when the suggestion
is nonsense.

| Dish shape | Vessel |
|---|---|
| gravy / curry | karahi or deep ceramic bowl |
| rice / biryani | wide flat plate or copper handi |
| burger / sandwich / wrap | wooden board or lined basket |
| fries / nuggets / popcorn chicken | paper cone, fry basket, or tray |
| shake / mocktail / coffee | tall glass, appropriate to the drink |
| dessert / ice cream | small bowl or dessert coupe |
| bread / roti / naan | flat plate or cloth-lined basket |
| whole roast / bucket | platter or branded bucket |

> **Note on existing behaviour:** the hardcoded kadhai/green-background wording
> was knowingly left in place earlier. It is being replaced now only because
> this spec explicitly requires reference-driven dynamic prompting — the
> replacement is derived from whatever reference the admin uploads, so it can
> never go stale again.

---

## 6. Confidence classification — one call per ~40 items

After extraction, a **single** `gemini-2.5-flash` structured call handles a
batch of items and returns, per item:

```json
{ "name": "Paneer Toofani Angara",
  "confidence": 65,
  "reason": "Regional house name; 'Toofani' and 'Angara' are style descriptors, not a fixed recipe",
  "concept": "Paneer cubes in a fiery red, smoky charred gravy with visible char and a cream swirl",
  "vessel": "karahi",
  "props": ["fresh coriander", "charred dry red chilli"],
  "product_category": "Other Food and Grocery" }
```

This one call does **four** jobs at once (confidence, concept card, vessel,
Excel category) — that is the token-efficiency win. ~100 items is ~3 calls total.

| Score | Bucket | Behaviour |
|---|---|---|
| >= 90 | High | auto-approved, straight to the generation queue |
| 60–89 | Moderate | held for review, concept card shown |
| < 60 | Low | held, flagged, concept card + "upload a reference" prompt |

Review screen per flagged item: **Approve concept** / **Edit concept text** /
**Upload own reference** / **Skip item**. Bulk-approve-all is one click.

---

## 7. Excel export — getting to zero manual corrections

Confirmed by reading the template: 25 columns, 29 data validations, and column
H (Product Category) is **free text with a 100-char cap**, *not* a dropdown.
Valid food values (named range `Food_And_Grocery`) are exactly 15 strings:

```
Fruits & Vegetables | Food grains, Oil & Masala | Bakery | Dairy | Beverages
Eggs, Meat & Seafood | Namkeen, Snacks & Biscuits | Health food | Instant Food
Chocolates, desserts and icecream | Mithai (Indian Sweets) | Baby food
Gourmet Food | Pet food | Other Food and Grocery
```

Today's exporter keyword-maps every row into just **2** of those 15. We replace
that with the AI-suggested `product_category` (§6), constrained to the 15, with
the existing keyword map retained as fallback.

Pre-export validation blocks the download on: name > 200 chars, description >
2000, MRP <= 0 or > 999999.99 or > 2 decimals, selling price > MRP, category
not in the valid list, missing image URL. Each failure is clickable and jumps
to that row.

Export still fills a **copy of the real template**, so all 29 validations survive.

---

## 8. API surface

```
POST   /api/auth/login              {username,password} -> session cookie
POST   /api/auth/logout
GET    /api/auth/me                 -> user + whether a gemini key is stored
PUT    /api/auth/gemini-key         {key} -> validated live, then encrypted
DELETE /api/auth/gemini-key

GET    /api/shops                        POST /api/shops
GET    /api/shops/{id}                   PATCH /api/shops/{id}
POST   /api/shops/{id}/reference    upload -> derives style_profile
POST   /api/shops/{id}/menus        upload 1..n menu photos

POST   /api/shops/{id}/jobs/extract      -> job id
POST   /api/shops/{id}/jobs/classify
POST   /api/shops/{id}/jobs/generate     {item_ids?}
POST   /api/shops/{id}/jobs/host
POST   /api/shops/{id}/jobs/export
GET    /api/jobs/{id}               -> status + counters
POST   /api/jobs/{id}/step          -> generate EXACTLY ONE item, then return
                                       {item, ok, next_delay_ms, remaining,
                                        retry_after_ms?}  <- the pacing loop
POST   /api/jobs/{id}/cancel
GET    /api/jobs/{id}/events        -> recent log lines (polled, not SSE:
                                       free hosts buffer streamed responses)

GET    /api/shops/{id}/items        filter by status / confidence / category
PATCH  /api/items/{id}              edit any field
POST   /api/items/{id}/approve  |  /hold  |  /skip  |  /regenerate
POST   /api/items/{id}/reference    upload a per-dish reference

GET    /api/images/{id}             bytes;  ?download=1 -> attachment
GET    /api/shops/{id}/images.zip   bulk download
GET    /api/exports/{id}            the .xlsx
```

---

## 9. Screens

1. **Login** — username/password, then "Paste your Gemini key" if none stored.
2. **Shops** — cards, progress ring, resume button, created-by, archive.
3. **Setup** — the 4 inputs: menu photos (drag-drop, multi), reference image
   (live preview + detected style chips), the 7 context metrics, ImgBB key.
4. **Review** — the heart. Two tabs: *Auto-approved (73)* / *Needs review (27)*.
   Each review card shows name, price, category, confidence bar, concept text
   and the 4 actions. Bulk approve. Keys: `a` approve, `h` hold, `s` skip, `j/k` move.
5. **Generate** — live grid, each tile animating pending → generating → done,
   SSE log drawer, current pacing delay + ETA, pause/resume, per-tile retry.
6. **Catalog** — final grid, inline edit, per-image download, regenerate,
   validation panel, **Export .xlsx**.

Every screen is resumable from the DB: closing the tab never loses state.

---

## 10. Repo layout

```
webapp/
  backend/
    app/
      main.py            FastAPI + SPA mount
      config.py  db.py  models.py  schemas.py  auth.py  storage.py
      routers/           auth shops menus items jobs images export
      engine/            pacer gemini extract classify prompt
                         generate imgbb export vessels
      stepper.py         claim-one-item + execute + persist (no bg thread)
    templates/smartbiz_template.xlsx
    tests/
    Dockerfile  requirements.txt
  frontend/
    src/  api/ components/ screens/ hooks/ lib/
    package.json  vite.config.ts  tailwind.config.ts
  docs/  PLAN.md  SPEC.md  DEPLOY.md
```

---

## 11. Build waves (orchestrator = Opus, workers = cheap agents)

`docs/SPEC.md` is written first — exact table DDL, pydantic schemas, function
signatures, API request/response shapes. Every agent reads only SPEC.md plus
the 1–2 files it owns, so no agent ever re-derives context. That is where the
token saving comes from.

| Wave | Agent | Owns | Reads |
|---|---|---|---|
| 0 | **Opus (me)** | SPEC.md, DDL, prompt design, vessel table | existing code (done) |
| 1a | cheap | scaffold, Dockerfile, config, db, models | SPEC §DDL |
| 1b | cheap | engine ports: pacer, gemini, imgbb, export | SPEC + 4 existing files |
| 1c | cheap | frontend scaffold, design system, API client | SPEC §API |
| 2a | cheap | auth + encryption + routers | SPEC §API |
| 2b | mid | stepper + job orchestration + DB-backed per-key pacing | SPEC + pacer |
| 2c | cheap | screens 1–3 | SPEC §Screens |
| 2d | cheap | screens 4–6 (review / generate / catalog) | SPEC §Screens |
| 3a | cheap | tests: schema, export validation, state machine | SPEC |
| 3b | **Opus (me)** | prompt engine + classify (highest judgement) | — |
| 4 | **Opus (me)** | integration, deploy to HF + Supabase, smoke test | — |

Every agent diff is reviewed before it lands. Agents never touch the pacing
code or the prompt engine.

---

## 12. Acceptance — "done" means

- [ ] Public https link. A teammate logs in from their own laptop and pastes their own Gemini key.
- [ ] Upload 3 menu photos + reference + 7 metrics + ImgBB key, and 100 items are extracted.
- [ ] Items split into confidence buckets; flagged ones show a text concept card.
- [ ] Approve / hold / manual-reference all work; batch runs only after review clears.
- [ ] Two different dishes get two different vessels and contextually correct props.
- [ ] Every image downloadable individually and as a zip; all persisted.
- [ ] Exported .xlsx uploads to SmartBiz with zero manual corrections.
- [ ] Close the tab mid-run, reopen, and the exact state is restored with no image regenerated.
- [ ] Two users run two shops at once on their own keys without 429-ing each other.
