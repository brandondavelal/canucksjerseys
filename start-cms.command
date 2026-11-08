#!/bin/bash
# Double-click to start the local CMS and open it in your browser.
cd "$(dirname "$0")"
(sleep 1; open "http://localhost:8765/collection-admin.html") &
exec python3 cms-server.py 8765
