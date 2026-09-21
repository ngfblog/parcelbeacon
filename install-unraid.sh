#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="parcelbeacon:1.0.0"
APPDATA_DIR="/mnt/cache/appdata/parcelbeacon"
TEMPLATE_DIR="/boot/config/plugins/dockerMan/templates-user"

if [[ ! -d /boot/config/plugins/dockerMan ]]; then
  echo "Error: this installer must run on an Unraid server."
  exit 1
fi

mkdir -p "${APPDATA_DIR}" "${TEMPLATE_DIR}"
chown 99:100 "${APPDATA_DIR}"
docker build --pull --tag "${IMAGE_NAME}" "${PROJECT_DIR}"
install -m 0644 "${PROJECT_DIR}/unraid/my-parcelbeacon.xml" "${TEMPLATE_DIR}/my-parcelbeacon.xml"

echo
echo "ParcelBeacon image and Unraid template are ready."
echo "Open Docker > Add Container and select ParcelBeacon from the Template list."
echo "Generate the Secret Key with: openssl rand -hex 32"
