# DEPLOY.md — getting to a clickable link, for ₹0

Total cost: nothing. No credit card on any service below.

Read §0 first — there is one prerequisite I cannot do for you.

---

## 0. What you need before starting

| # | Thing | Cost | Card? | Who does it |
|---|---|---|---|---|
| 1 | A **GitHub** account + this code pushed to a repo | free | no | you (I can run the commands) |
| 2 | A **Supabase** account + one project | free | no | **you** |
| 3 | A container host account (see §3) | free | no | you |
| 4 | An **ImgBB** API key | free | no | you already have one |
| 5 | A **Gemini express key** (`AQ.…`) per user | free | no | each user pastes their own after login |

Free container hosts deploy **from a Git repo**, so step 1 is unavoidable.
Make the repo **private** — `.gitignore` keeps `.env` out, but the repo will
still contain your prompts and business logic.

---

## 1. Generate the secrets

Run this once and keep the output somewhere safe:

```bash
python - <<'PY'
import secrets, json
from cryptography.fernet import Fernet
print("SESSION_SECRET =", secrets.token_urlsafe(48))
print("FERNET_KEY     =", Fernet.generate_key().decode())
print("APP_USERS      =", json.dumps([
    {"username": "omkar",   "password": "CHANGE-ME-1"},
    {"username": "teammate","password": "CHANGE-ME-2"},
]))
PY
```

Rules:
- **`FERNET_KEY` is not rotatable without cost.** It encrypts every stored
  Gemini and ImgBB key. Change it and every stored key becomes undecryptable
  and must be re-entered. Set it once.
- `APP_USERS` seeds accounts on boot. It **only inserts missing usernames** —
  editing a password here does *not* change an existing user's password.
- Use real passwords. This app is on a public URL; the login is the only gate.
  (Failed logins are throttled: 8 attempts per IP+username, then 5 minutes.)

---

## 2. Supabase — database + image storage

1. supabase.com → **New project**. Pick the region closest to you
   (`ap-south-1` Mumbai for India). Save the database password it shows you.
2. **Settings → Database → Connection string → URI**, and take the
   **Connection pooling** one (port `6543`), not the direct `5432` one. Free
   hosts open and drop connections constantly; the pooler is what keeps that
   from exhausting Postgres.
   Then convert the scheme for the async driver:
   ```
   postgresql://...        ->  postgresql+asyncpg://...
   ```
   That becomes `DATABASE_URL`.
3. **Settings → API**: copy the **Project URL** (`SUPABASE_URL`) and the
   **`service_role`** key (`SUPABASE_SERVICE_KEY`).
   The `service_role` key bypasses row-level security. It lives **only** in the
   server's env vars and must never appear in the frontend.
4. **Storage → New bucket** named `menu-catalog`. Keep it **private** — images
   are served through the app's own authenticated `/api/images/{id}` route.

Tables are created automatically on first boot. There are no migrations to run.

> Free Supabase projects pause after **7 days** of no activity. Daily use means
> you will never see this. If it does pause, un-pause it from the dashboard;
> no data is lost.

---

## 3. Pick a container host

The app is now an ordinary short-request web service — the browser drives the
generation loop, so **no background worker is required** (see PLAN.md §1.2).
That makes the host swappable. Try them in this order and stop at the first one
that works without asking for a card:

| Host | Free tier | Notes |
|---|---|---|
| **Render** | Web Service, 750 hrs/month | Spins down after 15 min idle; ~1 min cold start. Card policy varies by region — if it asks for one, move to the next. |
| **Koyeb** | one small service | No spin-down on some plans. |
| **Northflank** | free developer sandbox | Generous, slightly more setup. |
| **Google Cloud Run** | 2M requests/month | Excellent free tier, but GCP signup wants a card. |

All four take the same Dockerfile unchanged.

### Render (the default path)

1. Push this code to GitHub (§4).
2. Render → **New → Web Service** → connect the repo.
3. Settings:
   - **Runtime / Language:** Docker
   - **Dockerfile path:** `./Dockerfile`
   - **Docker build context:** `.`
     (the repo root IS the app: `webapp/` was pushed AS the repository root,
     so there is no `webapp/` prefix inside the repo)
   - **Health check path:** `/api/health`
   - **Instance type:** Free
4. Add every env var from §5.
5. Deploy. First build takes ~5 minutes (it builds the React app too).

Your link is `https://<service-name>.onrender.com`.

---

## 4. Push to GitHub

Already done: `webapp/` was pushed as the **repository root** of
https://github.com/Lolxd-1/Image-Generator, so the repo has `backend/`,
`frontend/`, `docs/` and `Dockerfile` at its top level. For later pushes:

```bash
cd webapp
git add -A && git commit -m "..."
git push
```

Note: `git init` defaults the branch to `master` while the remote expects
`main` — `git branch -M main` once, and that mismatch goes away.

Confirm `.env` is **not** in the commit before pushing:

```bash
git ls-files | grep -i "\.env$" && echo "STOP - .env is staged" || echo "OK - no .env"
```

---

## 5. Environment variables to set on the host

```
DATABASE_URL          postgresql+asyncpg://postgres.xxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
SUPABASE_URL          https://xxxx.supabase.co
SUPABASE_SERVICE_KEY  eyJhbGci...          # service_role, server-side only
SUPABASE_BUCKET       menu-catalog
SESSION_SECRET        <from §1>
FERNET_KEY            <from §1>
APP_USERS             [{"username":"omkar","password":"..."}]
STORAGE_BACKEND       supabase
```

`GEMINI_API_KEY` is deliberately **absent**. Keys are per-user: each person
pastes their own after logging in, and it is encrypted before it is stored.
That is what gives 3–4 people independent rate limits instead of one shared
bottleneck.

---

## 6. Verify the deployment

In order — each step proves the layer under it:

1. `curl https://<your-app>/api/health` → `{"status":"ok"}` (app is up)
2. Open the URL, log in with an `APP_USERS` account (DB reachable, seeding ran)
3. Paste a Gemini express key → it is validated with a live call before being
   accepted, so a bad key fails here rather than 40 minutes into a batch
4. Create a shop, upload a reference image → "detected style" chips appear
   (Gemini vision + Supabase Storage both working)
5. Upload a menu photo → items extract with confidence scores
6. Generate **two or three** items only, and check the vessels differ
7. Host → ImgBB URLs appear
8. Export → open the `.xlsx` and confirm the dropdowns survived

Do **not** launch a 100-item run until steps 1–8 pass. That is an hour of
quota; find problems on three items instead.

---

## 7. Operating notes

**Keep the tab open during generation.** The browser drives the pacing loop.
Closing it pauses the run — nothing is lost, no image is regenerated, and
reopening the Generate screen continues from exactly where it stopped. This is
a deliberate trade for zero-cost hosting (PLAN.md §1.2).

**First click after idle is slow.** A free host spins down after ~15 minutes;
the first request wakes it in about a minute. During an active run, requests
every ~30s keep it awake by construction.

**Pacing self-tunes per key.** Starts at 30s between images, ×1.5 slower on
every 429, ×0.92 faster on every success, bounded to 8–120s. State lives in the
`pace_state` table keyed by API key hash, so it survives restarts and host
swaps, and one person's 429 never slows another person's run.

**If ImgBB returns "Internal upload error" (code 111)** that is an account-level
cap on that key, not a problem with the images. Retrying achieves nothing, so
the host job stops immediately and says so. Put a different ImgBB key on the
shop and re-run the host step. Generated images are safe in Supabase Storage —
nothing needs regenerating.

**Storage budget.** Supabase free gives 1 GB ≈ 3,000 dish images at ~340 KB
each. Archive old shops when it fills.

---

## 8. Moving to another host later

Nothing in the code is host-specific: it is a plain Docker container reading
env vars. To move, point the new host at `webapp/Dockerfile`, copy the same env
vars, and redeploy. Supabase and ImgBB do not change, so **no data migrates and
no images are regenerated**. If you later want an always-on instance with no
cold start and no open-tab requirement, the same image runs on any paid tier —
and only then does adding a background worker become worth doing.
