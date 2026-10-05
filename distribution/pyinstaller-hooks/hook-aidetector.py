"""Keep the build reference outside the frozen archive.

`aidetector/version.py` is the only part of a frozen detector that differs between two
builds of the same sources. Collected as a plain file, it can be rewritten when a tested
detector is reused for a later build (see `stamp_detector` in build.py).
"""

module_collection_mode = {"aidetector.version": "py"}
