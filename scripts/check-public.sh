#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

if [[ -f .env ]]; then
  echo "Error: .env exists in the project directory. Do not publish it."
  exit 1
fi

if find . -type f \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' \) -print -quit | grep -q .; then
  echo "Error: a runtime database file exists in the project directory."
  exit 1
fi

if grep -RInE \
  --exclude='check-public.sh' \
  --exclude-dir='.git' \
  --exclude-dir='__pycache__' \
  --exclude-dir='.pytest_cache' \
  '(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})' .; then
  echo "Error: a private IPv4 address was found. Replace it with a placeholder."
  exit 1
fi

echo "Public repository privacy check passed."
