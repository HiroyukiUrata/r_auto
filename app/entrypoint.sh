#!/bin/bash

# Start virtual framebuffer on display :0
Xvfb :0 -screen 0 1280x960x24 &

# Start VNC server, listening on port 5900, without a password
x11vnc -display :0 -forever -nopw &

# Execute the main application command passed to this script
exec "$@"