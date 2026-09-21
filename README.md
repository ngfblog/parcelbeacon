# ParcelBeacon

ParcelBeacon is a lightweight, single-user shipment dashboard designed for Unraid. It stores shipment metadata and event history locally in SQLite, polls TrackingMore API v4, and sends status-change notifications through Gotify.

## Features

- Responsive web dashboard
- Automatic carrier detection
- Automatic background polling
- Shipment event history
- Archive and restore workflow
- Gotify notifications only when a shipment changes
- SQLite storage with WAL mode
- Optional login protection
- Account page for changing the login username and password
- Docker health check and log rotation

## Requirements

- Unraid with Docker Compose or Portainer
- A TrackingMore API key for automatic tracking
- Optional Gotify server and application token

## Recommended installation on Unraid

1. Extract the project to `/mnt/user/appdata/parcelbeacon-project`.
2. Open an Unraid terminal and run:

   ```bash
   cd /mnt/user/appdata/parcelbeacon-project
   chmod +x install-unraid.sh
   ./install-unraid.sh
   ```

3. Open **Docker > Add Container**.
4. Select **ParcelBeacon** from the **Template** list.
5. Generate a session key with `openssl rand -hex 32` and paste it into **Secret Key**.
6. Enter a username, a strong password, and optional TrackingMore and Gotify credentials.
7. Keep **Network Type** set to **Bridge**, then click **Apply**.
8. Open `http://UNRAID-IP:8090`.

The installer builds the local `parcelbeacon:1.0.0` image and installs one Unraid XML template. No registry image is required.
The persistent appdata directory is assigned to Unraid's standard `nobody:users` ownership (`99:100`).

## Docker Compose installation

1. Extract the project to `/mnt/user/appdata/parcelbeacon-project`.
2. Open a terminal in that directory.
3. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

4. Generate a session secret:

   ```bash
   openssl rand -hex 32
   ```

5. Edit `.env` and set `SECRET_KEY`, `APP_PASSWORD`, `TRACKINGMORE_API_KEY`, and `GOTIFY_TOKEN`.
6. Build and start the container:

   ```bash
   docker compose up -d --build
   ```

7. Open `http://UNRAID-IP:8090`.

Persistent data is stored in `/mnt/cache/appdata/parcelbeacon`.

## Configuration

| Variable | Required | Default | Description |
|---|---:|---|---|
| `SECRET_KEY` | Yes | None | Flask session signing secret |
| `APP_USERNAME` | No | `admin` | Web login username |
| `APP_PASSWORD` | Recommended | Empty | Enables login protection when set |
| `TRACKINGMORE_API_KEY` | For updates | Empty | TrackingMore API v4 key |
| `POLL_INTERVAL_MINUTES` | No | `60` | Poll interval; minimum is 15 minutes |
| `GOTIFY_URL` | No | Empty | Gotify base URL |
| `GOTIFY_TOKEN` | No | Empty | Gotify application token |

`APP_USERNAME` and `APP_PASSWORD` provide the initial login credentials. After the
first login, both values can be changed from **Account Settings** in the web UI.
Web-managed credentials are stored in the SQLite database, and the password is
stored only as a salted hash. The web-managed credentials take precedence over
the container environment variables.

## Backup

Back up `/mnt/cache/appdata/parcelbeacon`. The SQLite database is the only persistent application file. For a consistent live backup, use SQLite's backup command or stop the container before copying the directory.

## Update

```bash
cd /mnt/user/appdata/parcelbeacon-project
docker compose down
docker compose up -d --build
```

## Security

- Do not expose port 8090 directly to the internet.
- Use a reverse proxy with HTTPS for remote access, or access it through Tailscale.
- Keep `.env` private and never commit it to Git.
- Use a unique Gotify application token.
- Run `./scripts/check-public.sh` before publishing changes.

## Provider notes

ParcelBeacon does not scrape carrier websites. Automatic updates require a supported tracking API. Carrier availability, quotas, and pricing are controlled by TrackingMore. The dashboard remains usable without an API key for manually recording and organizing tracking numbers.

## License

MIT
