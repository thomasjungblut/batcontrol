#!/bin/sh
set -e

CONFIG_FILE="/app/config/batcontrol_config.yaml"

if test ! -e "/app/config/.init" ; then
  echo "Initializing config file from template"
  # Copy files but don't overwrite
  cp -nv /app/config_template/* /app/config
  echo "$BATCONTROL_VERSION" >  /app/config/.init
fi

# Check if the config file is available
if test ! -f "$CONFIG_FILE" ; then
  echo "Config file not found: $CONFIG_FILE"
  echo "Copying dummy config for first startup..."
  cp /app/config_template/batcontrol_config_dummy.yaml "$CONFIG_FILE"
  echo "IMPORTANT: Dummy configuration copied!"
  echo "          Please edit $CONFIG_FILE: Fronius address, user, password,"
  echo "          max_grid_charge_rate and your Tibber api_token."
  echo ""
fi

# Print BATCONTROL_VERSION and BATCONTROL_GIT_SHA
echo "BATCONTROL_VERSION: $BATCONTROL_VERSION"
echo "BATCONTROL_GIT_SHA: $BATCONTROL_GIT_SHA"

# Workaround for non configurable logfile path
# Create a symlink to /app/log/batcontrol.log
if test ! -e "/app/logs/batcontrol.log" ; then
  touch /app/logs/batcontrol.log
  ln -s /app/logs/batcontrol.log /app/batcontrol.log
fi

# Output the timezone
echo "Current local time is: $(date)"
echo "Configured timezone (env var TZ) is: $TZ"

# Start batcontrol.py
exec python -m batcontrol "$@"
