"""Stands in for the command the separate detector image ran before the single image.

A container created from that image keeps its command when a tool updates only the image, and
without this file it would restart forever on a missing file.
"""

import sys

MESSAGE = """\
This container still runs the command of the old ai-detector image:
    python3 src/aidetector/__init__.py
The image now starts the web application, which runs the detector itself, with:
    node /app/node-server.mjs

Recreate the container so it takes the new command, for example:
    docker compose up -d --force-recreate
In Portainer, Synology Container Manager or a similar tool, delete the container and create it
again from the Compose file instead of only updating its image.

Coming from the two images ai-detector and ai-detector-web, follow
https://github.com/ESchouten/ai-detector/blob/main/detector/MIGRATION.md#docker
"""

sys.stderr.write(MESSAGE)
sys.exit(1)
