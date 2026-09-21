# ParcelBeacon

ParcelBeacon is a lightweight, single-user shipment dashboard designed for Unraid. It stores shipment metadata and event history locally in SQLite, uses Track123 as the primary tracking provider with an optional Ship24 fallback, and sends status-change notifications through Gotify.

## Features

- Responsive Hebrew dashboard with compact horizontal shipment cards
- Sorting by nearest or farthest estimated delivery date
- Nearest estimated delivery is the default sort order
- Search by shipment name, tracking number, store, courier, provider, status, or event
- Automatic carrier detection
- Track123 primary provider with automatic Ship24 fallback
- Tracking provider shown for every shipment
- Automatic background polling
- Shipment event history
- Shipment editing, including tracking number corrections
- Source selection with a replaceable preset list and custom text entry
- Direct link to the Ship24 shipment dashboard
- Optional local product images with metadata removal and resizing
- Hebrew tracking descriptions and Israel-local date formatting
- Clear detected courier display
- Archive and restore workflow
- Permanent shipment deletion with browser confirmation
- Gotify notifications only when a shipment changes
- SQLite storage with WAL mode
- Optional login protection
- Account page for changing the login username and password
- Docker health check and log rotation

## Requirements

- Unraid with Docker Compose or Portainer
- A Track123 API key for automatic tracking
- Optional Ship24 API key for fallback tracking
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
6. Enter a username, a strong password, a Track123 API key, and optional Ship24 and Gotify credentials.
7. Keep **Network Type** set to **Bridge**, then click **Apply**.
8. Open `http://UNRAID-IP:8090`.

The installer pulls `ghcr.io/ngfblog/parcelbeacon:latest` and installs the Unraid XML template.
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

5. Edit `.env` and set `SECRET_KEY`, `APP_PASSWORD`, `TRACK123_API_KEY`, and any optional Ship24 or Gotify credentials.
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
| `TRACK123_API_KEY` | For updates | Empty | Primary Track123 Tracking API key |
| `SHIP24_API_KEY` | No | Empty | Optional Ship24 fallback API key |
| `DESTINATION_COUNTRY_CODE` | No | `IL` | Destination country hint used to improve courier detection |
| `POLL_INTERVAL_MINUTES` | No | `60` | Poll interval; minimum is 15 minutes |
| `GOTIFY_URL` | No | Empty | Gotify base URL |
| `GOTIFY_TOKEN` | No | Empty | Gotify application token |

`APP_USERNAME` and `APP_PASSWORD` provide the initial login credentials. After the
first login, both values can be changed from **Account Settings** in the web UI.
Web-managed credentials are stored in the SQLite database, and the password is
stored only as a salted hash. The web-managed credentials take precedence over
the container environment variables.

## Backup

Back up `/mnt/cache/appdata/parcelbeacon`. It contains the SQLite database and the optional `uploads` directory with product images. For a consistent live backup, use SQLite's backup command or stop the container before copying the directory.

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

ParcelBeacon does not scrape carrier websites. Track123 is queried first. Ship24 is queried only when Track123 is unavailable or does not yet provide useful tracking data. Carrier availability, quotas, and pricing are controlled by the providers. The dashboard remains usable without an API key for manually recording and organizing tracking numbers.

## License

MIT
