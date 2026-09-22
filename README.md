# ParcelBeacon

ParcelBeacon is a lightweight, single-user shipment dashboard designed for Unraid. It stores shipment metadata and event history locally in SQLite, uses Track123 for tracking, and sends status-change notifications through Gotify.

## Features

- Responsive Hebrew dashboard with compact horizontal shipment cards
- Compact single-line page heading and collapsible add-shipment form
- Sorting by nearest or farthest estimated delivery date
- Nearest estimated delivery is the default sort order
- Search by shipment name, tracking number, store, courier, provider, status, or event
- Automatic carrier detection
- Track123 tracking provider
- Tracking provider shown for every shipment
- Automatic background polling
- Shipment event history
- Shipment editing, including tracking number corrections
- Source selection with a replaceable preset list and custom text entry
- Optional local product images with metadata removal and resizing
- Optional product-page URL on each shipment, editable later and linked from its card and detail page
- Hebrew labels and translations for common Track123, Cainiao, and FedEx tracking events, including repeated provider messages
- Larger status text on compact cards and Israel-local date formatting
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
6. Enter a username, a strong password, a Track123 API key, and optional Gotify credentials.
7. Keep **Network Type** set to **Bridge**, then click **Apply**.
8. Open `http://UNRAID-IP:8090`.

The installer pulls `ghcr.io/ngfblog/parcelbeacon:latest` and installs the Unraid XML template.
The persistent appdata directory is assigned to Unraid's standard `nobody:users` ownership (`99:100`).
The installer uses the image currently published to GHCR; extracting new project files alone does not update that image.

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

5. Edit `.env` and set `SECRET_KEY`, `APP_PASSWORD`, `TRACK123_API_KEY`, and optional Gotify credentials.
6. Build and start the container:

   ```bash
   docker compose up -d --build
   ```

7. Open `http://UNRAID-IP:8090`.

Persistent data is stored in `/mnt/cache/appdata/parcelbeacon`.

## Adding and editing shipments

1. Open **Add shipment** and enter a tracking number. A name, carrier code, store/source, product image, and product-page URL are optional.
2. For a product page, paste its full `https://` or `http://` URL into **Product page URL**. The dashboard and shipment details will show a link that opens it in a new tab.
3. Open **Edit** on an existing shipment to correct any of these values. Clear the product-page URL field and save to remove the link.
4. Use **Refresh** for one shipment or **Refresh all** to request new provider data. Automatic polling uses `POLL_INTERVAL_MINUTES` and runs while the container is running.

Product images are stored locally in the persistent `uploads` directory. The product-page URL is stored as text; ParcelBeacon does not fetch the product page or extract a product name or image from it. If a shipment name is left empty, ParcelBeacon generates a local name from the source or tracking number.

## Configuration

| Variable | Required | Default | Description |
|---|---:|---|---|
| `SECRET_KEY` | Yes | None | Flask session signing secret |
| `APP_USERNAME` | No | `admin` | Web login username |
| `APP_PASSWORD` | Recommended | Empty | Enables login protection when set |
| `TRACK123_API_KEY` | For updates | Empty | Primary Track123 Tracking API key |
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

## Updating

### Unraid template using GHCR

The Unraid template points to `ghcr.io/ngfblog/parcelbeacon:latest`. First publish the updated project through the repository's **Build and Publish Container** workflow and confirm the workflow succeeded. Then use Unraid's **Check for Updates** and **Update** for the ParcelBeacon container. A source ZIP or a new README does not change the running GHCR container until an updated image is published and pulled.

Keep the existing `/data` mapping to `/mnt/cache/appdata/parcelbeacon`. Shipment records, saved login settings, and product images remain in that persistent directory. Database columns needed by newer versions are added automatically at startup.

### Docker Compose built from local project files

Extract the full updated project over your local source directory, keeping the persistent appdata directory separate. From the project directory, rebuild and restart:

```bash
cd /mnt/user/appdata/parcelbeacon-project
docker compose up -d --build
```

Confirm the container started with `docker compose ps` and review its logs with `docker compose logs --tail=100 parcelbeacon`. Reload the dashboard in the browser. When changing installation methods, check that both methods mount the same host appdata directory to `/data` before starting the replacement container.

## Security

- Do not expose port 8090 directly to the internet.
- Use a reverse proxy with HTTPS for remote access, or access it through Tailscale.
- Keep `.env` private and never commit it to Git.
- Use a unique Gotify application token.
- Run `./scripts/check-public.sh` before publishing changes.

## Provider notes

ParcelBeacon does not scrape carrier websites. Track123 is queried for tracking updates and automatically identifies carriers when no carrier code is supplied. A detected carrier is shown even if no tracking events are available yet. To correct an identification, enter its Track123 carrier code (for example, `royal-mail` or `aramex`) in Edit shipment; the selected carrier is sent during registration and subsequent queries. For an existing registered tracking, the app requests a carrier change from Track123 before querying again. A correctly detected carrier does not guarantee that Track123 has access to tracking events. Carrier availability, quotas, and pricing are controlled by the provider. Common tracking event messages are translated for display in Hebrew; messages without a known translation can still appear in their original language. The dashboard remains usable without an API key for manually recording and organizing tracking numbers.

## License

MIT
