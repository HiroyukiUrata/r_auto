#!/bin/bash

# Remove stale X11 lock files
rm -f /tmp/.X0-lock
rm -rf /tmp/.X11-unix/

# Set DISPLAY
export DISPLAY=:0

# Start virtual framebuffer
Xvfb :0 -screen 0 1280x960x24 &

# Wait for Xvfb
sleep 2

# Start VNC server
x11vnc -display :0 -forever -nopw &

# Start Python app
echo "Starting Python application (FastAPI server and scheduler)..."
python -m app.main &

# Keep container running
echo "Entrypoint setup complete. Container is running."
exec sleep infinity
