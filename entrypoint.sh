#!/bin/sh
set -e

CONFIG_FILE="/app/config/batcontrol_config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
  cp /app/config_template/batcontrol_config_dummy.yaml "$CONFIG_FILE"
  echo "No config found - copied a template to $CONFIG_FILE."
  echo "Edit it (Fronius address, user, password, max_grid_charge_rate,"
  echo "Tibber api_token) and restart the container."
  exit 1
fi

echo "batcontrol ${BATCONTROL_VERSION} (${BATCONTROL_GIT_SHA}), TZ=${TZ}, local time $(date)"
exec python -m batcontrol --config "$CONFIG_FILE" "$@"
