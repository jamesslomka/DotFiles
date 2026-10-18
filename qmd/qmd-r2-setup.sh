#!/usr/bin/env bash
#
# One-time: point rclone at a Cloudflare R2 bucket for qmd-r2-backup.sh.
#
# You need, from the Cloudflare dashboard (R2 > Manage R2 API Tokens):
#   - account ID (shown on the R2 overview page, 32 hex chars)
#   - an API token with "Object Read & Write" scoped to the backup bucket
#     -> gives an Access Key ID and a Secret Access Key
#   - the bucket name (create it under R2 > Create bucket first)
#
# Values can be passed as env vars (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY, R2_BUCKET) or you will be prompted. The secret is read
# without echo and written only to ~/.config/rclone/rclone.conf (mode 600).

set -euo pipefail

command -v rclone >/dev/null || { echo "rclone not installed (brew install rclone)" >&2; exit 1; }

REMOTE="${R2_REMOTE_NAME:-r2}"
ACCOUNT="${R2_ACCOUNT_ID:-}"
KEY="${R2_ACCESS_KEY_ID:-}"
SECRET="${R2_SECRET_ACCESS_KEY:-}"
BUCKET="${R2_BUCKET:-qmd-backup-work}"

[ -n "$ACCOUNT" ] || read -rp "Cloudflare account ID: " ACCOUNT
[ -n "$KEY" ]     || read -rp "R2 Access Key ID: " KEY
if [ -z "$SECRET" ]; then read -rsp "R2 Secret Access Key: " SECRET; echo; fi
read -rp "Bucket name [$BUCKET]: " b; BUCKET="${b:-$BUCKET}"

case "$ACCOUNT" in
  *[!0-9a-f]*|"") echo "account ID should be 32 hex chars" >&2; exit 1 ;;
esac

rclone config create "$REMOTE" s3 \
  provider=Cloudflare \
  access_key_id="$KEY" \
  secret_access_key="$SECRET" \
  endpoint="https://$ACCOUNT.r2.cloudflarestorage.com" \
  acl=private \
  no_check_bucket=true \
  --non-interactive >/dev/null
chmod 600 "$HOME/.config/rclone/rclone.conf"

mkdir -p "$HOME/.config/qmd"
printf 'QMD_BACKUP_DEST=%s:%s\n' "$REMOTE" "$BUCKET" > "$HOME/.config/qmd/backup.env"

echo "testing access to $REMOTE:$BUCKET ..."
if rclone lsd "$REMOTE:$BUCKET" >/dev/null 2>&1 || rclone lsf "$REMOTE:$BUCKET" >/dev/null 2>&1; then
  echo "ok. remote '$REMOTE' -> $BUCKET"
else
  echo "could not list $REMOTE:$BUCKET. Check the bucket exists and the token is scoped to it." >&2
  exit 1
fi

echo
echo "Next:  ~/bin/qmd-r2-backup.sh sync      (first upload)"
echo "       ~/bin/qmd-r2-backup.sh status"
