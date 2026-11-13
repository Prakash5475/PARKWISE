# PARKWISE Web Edition — deployment guide

This is a browser-based companion to the original Python/Tkinter project. The desktop application remains in the repository unchanged. The web edition has a React/Vite frontend and a FastAPI backend.

## Architecture

- `web/frontend`: React + Vite dashboard and animated three-floor garage view.
- `web/backend`: FastAPI REST API + WebSocket live slot feed.
- Backend database: SQLite. The Render blueprint mounts a persistent disk at `/var/data` so sessions survive service restarts. The persistent disk requires a paid Render web-service plan; do not deploy this SQLite setup to an ephemeral free instance if you need durable data.
- Frontend hosting: Vercel.

## Deploy the backend to Render

1. Push the complete repository to GitHub.
2. In Render, create **New → Blueprint** and select the repository.
3. Render reads `web/backend/render.yaml` (if the dashboard asks for a blueprint file path, choose that file).
4. Confirm the service uses the `starter` plan and the persistent disk mount `/var/data`.
5. Deploy. The health endpoint is `https://YOUR-API.onrender.com/api/health`.
6. Keep the generated API URL; it is needed for the frontend.

If creating the service manually instead: root directory `web/backend`; build command `pip install -r requirements.txt`; start command `uvicorn main:app --host 0.0.0.0 --port $PORT`; environment variable `DATABASE_PATH=/var/data/parkwise.db`; attach a persistent disk mounted at `/var/data`.

## Deploy the frontend to Vercel

1. In Vercel, import the same GitHub repository.
2. Set **Root Directory** to `web/frontend`.
3. Framework preset: Vite. Build command: `npm run build`. Output directory: `dist`.
4. Add environment variable `VITE_API_URL` with the Render API origin, for example `https://YOUR-API.onrender.com` (no trailing slash).
5. Deploy. The Vercel URL is the public PARKWISE website.

## Run locally

Terminal 1:

```bash
cd web/backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Terminal 2:

```bash
cd web/frontend
npm install
# Windows PowerShell: $env:VITE_API_URL="http://localhost:8000"
# macOS/Linux: export VITE_API_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:5173`.

## Implemented web features

- 54 bays over ground, first and second floors, retaining the original bay categories.
- Vehicle registration, nearest suitable bay allocation and a three-vehicle waiting queue.
- Car / Bike / EV / VIP categories and the original hourly rates.
- 5-minute grace period and 18% GST checkout calculation.
- Two-hour reservations, cancellation, session history and CSV export.
- Live overview, animated garage visualization, floor selection, event feed and analytics.
- REST API and WebSocket endpoint (`/ws/live`).

## Important scope notes

- The web app is a new web interface and API. It preserves the documented facility layout, vehicle categories, rates, grace period, GST, and broad allocation/queue concepts, but it does **not** import the desktop app's existing `data/parking.db` automatically. The web database is initialized separately.
- The moving road vehicles and auto-arrival demo on the Live Monitor are a browser-side demonstration. They are not connected to physical cameras, sensors, gates or barriers.
- Payments are simulated. No UPI/card gateway is connected.
- The original six Python worker threads and Tkinter kinematic simulation remain part of the desktop app; they are not running as cloud threads in this web edition.
- The initial admin view is a demo facility dashboard without login/authentication. Add authentication and role permissions before using with real customer or vehicle data.
- This is a single-instance SQLite API. For multi-instance/high-volume production, migrate the API to PostgreSQL and add authentication, backups, monitoring and rate limiting.
