"""Exercise the patched executable bootstrap with a tiny SvelteKit-shaped server."""

import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


def server_fixture(folder: Path, adapter: Path) -> Path:
    entry = folder / "temp-server"
    entry.mkdir()
    source = adapter.read_text()
    beginning = source.index("function startMdnsResponder(")
    ending = source.index("function sendMdnsMulticast", beginning)
    source = (
        source[:beginning]
        + (
            "function startMdnsResponder() { const socket = createSocket('udp4'); "
            "socket.bind(0, '127.0.0.1'); return socket; }\n\n"
        )
        + source[ending:]
    )
    (entry / "index.ts").write_text(source)
    shutil.copy2(Path(__file__).with_name("desktop-instance.ts"), entry)
    (entry / "assets.generated.ts").write_text("export const assetMap = new Map();\n")
    (folder / "manifest.js").write_text(
        "export default { _: { prerendered_routes: new Set() }, appDir: '_app' };\n"
    )
    (folder / "server").mkdir()
    (folder / "server/index.js").write_text(
        "import { appendFileSync } from 'node:fs';\n"
        "process.once('sveltekit:shutdown', async () => { "
        "const response = await fetch('http://127.0.0.1:' + process.env.PORT + '/'); "
        "appendFileSync(process.env.AIDETECTOR_DATA_DIR + '/drained', String(response.status)); });\n"
        "export class Server { async init() { appendFileSync(process.env.AIDETECTOR_DATA_DIR + '/starts', 'started\\n'); } "
        "async respond() { return new Response('fixture dashboard'); } }\n"
    )
    return entry


@unittest.skipUnless(
    shutil.which("bun"), "Bun is required for executable launcher integration"
)
class LauncherTest(unittest.TestCase):
    def test_second_launch_does_not_initialize_another_server_and_quit_is_graceful(
        self,
    ):
        repo = Path(__file__).resolve().parent.parent
        adapter = (
            repo / "web/node_modules/@jesterkit/exe-sveltekit/dist/server/index.ts"
        )
        if not adapter.exists():
            self.skipTest("Install web dependencies before testing the adapter")
        with tempfile.TemporaryDirectory(prefix="ai-launcher-") as temporary:
            folder = Path(temporary)
            entry = server_fixture(folder, adapter)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            env = {
                **os.environ,
                "AIDETECTOR_DATA_DIR": str(folder / "data"),
                "HOST": "0.0.0.0",
                "PORT": str(port),
                "OPEN_BROWSER": "false",
            }
            arguments = [shutil.which("bun"), str(entry / "index.ts")]
            with (folder / "log").open("w+") as log:
                process = subprocess.Popen(arguments, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    starts = folder / "data/starts"
                    while (
                        not starts.exists()
                        and process.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.05)
                    self.assertTrue(
                        starts.exists(),
                        "Startup must initialize without a browser request",
                    )
                    second = subprocess.run(
                        [*arguments, "--background"],
                        env=env,
                        capture_output=True,
                        timeout=15,
                    )
                    self.assertEqual(second.returncode, 0, second.stderr.decode())
                    self.assertEqual(starts.read_text(), "started\n")
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=2
                    ) as response:
                        self.assertEqual(response.read(), b"fixture dashboard")
                    with subprocess.Popen(
                        [*arguments, "--quit"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    ) as quitting:
                        # Reap the owner while the helper waits; a POSIX zombie still has a PID.
                        process.wait(timeout=15)
                        _, errors = quitting.communicate(timeout=15)
                        self.assertEqual(quitting.returncode, 0, errors.decode())
                    self.assertEqual((folder / "data/drained").read_text(), "200")
                    self.assertFalse((folder / "data/desktop-instance.json").exists())
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                    log.seek(0)
                    print(log.read())
