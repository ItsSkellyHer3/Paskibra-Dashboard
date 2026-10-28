# Paskibra

A Flask web app for a Paskibra organization. It provides member accounts, attendance, schedules, announcements, member profiles, administration, QR workflows, and optional browser push notifications. Data is stored in a local SQLite database.

## Requirements

- Python 3.10 or newer
- `python3-venv` support (often included with Python)
- A free TCP port, 5000 by default

The built-in Flask server started by `run.sh` is for local development and basic internal use. For an internet-facing deployment, use a production WSGI server behind a reverse proxy with HTTPS. The included systemd example currently launches the built-in Flask server, so adapt it before relying on it for a public production service.

## Run locally

From the project directory:

```bash
./run.sh
```

On first run, the script creates `.venv`, installs packages from `requirements.txt`, creates runtime directories, and starts the app at `http://127.0.0.1:5000` (the startup message uses the configured host). Open `/auth/login` to sign in. The database schema is created and upgraded automatically on startup.

To choose a different port or bind address:

```bash
HOST=127.0.0.1 PORT=5001 ./run.sh
```

To stop the app, press Ctrl+C. For manual setup instead, create and activate a virtual environment, install requirements, then run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

## Configuration

The app reads configuration from environment variables. For local use, export them in your shell. For systemd, copy `.env.example` to `.env`, replace the sample secret, and restrict the file (for example, `chmod 600 .env`). The included service unit loads `.env` as an EnvironmentFile.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session signing key. Set a long, random value for every deployment and keep it private. |
| `PASKIBRA_OWNER_PASSWORD` | Optional first-owner bootstrap password. On startup, it creates or updates the `ItsSkellyHer3` Owner account. Remove this variable after the initial account setup. |
| `HOST` | Bind address for `run.sh`; defaults to `0.0.0.0`. Use `127.0.0.1` behind a local reverse proxy. |
| `PORT` | Listen port for `run.sh`; defaults to `5000`. |
| `VAPID_PRIVATE_KEY` | Optional Web Push private key. If omitted, the app creates and stores `instance/vapid_private.pem`; preserve this file across restarts and deployments. |
| `VAPID_PRIVATE_KEY_PATH` | Optional path to a PEM VAPID private key, used instead of `VAPID_PRIVATE_KEY` or the generated instance key. |
| `VAPID_PUBLIC_KEY` | Optional public key assertion; if set, it must match the private key. |
| `VAPID_SUBJECT` | Optional Web Push contact URI, such as `mailto:admin@example.org`. |

Generate a Flask secret with:

```bash
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Set the generated value as `SECRET_KEY` in the deployment environment. Never commit `.env`, private keys, production databases, or user uploads.

### First owner account

For a fresh installation, set `PASKIBRA_OWNER_PASSWORD` before the first app start. The app creates the Owner account with username `ItsSkellyHer3`. The password is stored as a hash. See [OWNER_SETUP.md](OWNER_SETUP.md) for the existing server's setup procedure. Be aware that setting the variable again on a later restart updates that account's password.

## Data and backups

- SQLite database: `paskibra_v2.db` in the project directory.
- Uploaded profile and announcement files: `static/uploads/`.
- Generated Web Push key: `instance/vapid_private.pem`.

Back up the database, uploads, and VAPID key together and keep the backup access restricted. Losing the VAPID private key invalidates existing browser push subscriptions. The database and uploaded files are intentionally ignored by Git.

## Deploy to the existing Linux server

`deploy.sh` synchronizes source files to `~/paskibra_v2`, backs up the existing server directory and service unit, preserves the server database/uploads/VAPID key, restarts the systemd service when present, and checks the local login endpoint on port 5000.

```bash
./deploy.sh user@your-server
```

If omitted, the script uses the maintainer's configured server address. Review the target before running it. The target needs SSH access, Python 3, and permission to install/restart the systemd service. The included `paskibra-v2.service` is configured for the original account and path (`adhyastha`, `/home/adhyastha/paskibra_v2`); adapt those values before installing it elsewhere. Configure HTTPS and a reverse proxy separately.

## Project layout

- `app.py` — Flask app factory, middleware, and shared routes
- `blueprints/` — authentication, dashboard, administration, attendance, schedules, members, profile, and notifications
- `database.py`, `schema.sql` — SQLite initialization and schema
- `templates/`, `static/` — user interface, assets, and service worker
- `utils/` — shared helpers and web-push support
- `run.sh` — local launcher
- `deploy.sh`, `paskibra-v2.service` — deployment and systemd examples

## Dependencies

Install pinned-compatible dependency ranges from `requirements.txt`:

- Flask
- Pillow
- qrcode with Pillow support
- py-vapid
- pywebpush

## License

No license is currently included. All rights remain with the copyright holder unless a license is added.
