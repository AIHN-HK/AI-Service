#!/bin/sh
# Ensure mounted directories are writable by appuser
chown -R appuser:appuser /app/logs /app/data 2>/dev/null || true

# Run the main command as appuser
exec gosu appuser "$@"
