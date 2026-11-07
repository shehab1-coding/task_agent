# Chatbot

## Deployment configuration

Set these values in the deployment platform before deploying this hardening branch:

- `SECRET_KEY`: a new, long, random secret. Startup fails if it is missing; only local development with `FLASK_DEBUG=1` may use a temporary key.
- `APP_ENV=production`: enables HTTPS-only origin checks. Railway deployments are detected automatically.
- `ADMIN_USERNAME` and `ADMIN_PASSWORD`: unique administrator credentials. The admin login is disabled until both are set.
- `GEMINI_API_KEYS`: one or more Gemini API keys separated by commas.
- `SESSION_COOKIE_SECURE=true`: keep enabled for HTTPS deployments such as Railway.
- `RATELIMIT_STORAGE_URI`: optional Redis URL for rate limits shared across multiple app workers. Without it, limits are stored in process memory.

The app serves its own frontend, so cross-origin access is disabled. Keep the SQLite database and its backup safe during deployment changes. The database file is ignored for future commits, but removing a file from Git does not erase it from earlier commit history; back up and migrate live data before removing the tracked database or rewriting repository history.

For local development, set `FLASK_DEBUG=1` before starting the app. Never enable it on a public deployment.
