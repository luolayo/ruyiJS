"""Select the local transport without loading Windows APIs on macOS."""

import os
import sys

if os.name == "nt":
    from ._pipe_windows import MAX_FRAME, Pipe
elif sys.platform == "darwin":
    from ._pipe_posix import MAX_FRAME, Pipe
else:
    raise OSError("ruyijs transport currently supports Windows and macOS")
