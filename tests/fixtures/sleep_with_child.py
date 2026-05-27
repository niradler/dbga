from __future__ import annotations

import subprocess
import sys
import time

if __name__ == "__main__":
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(60)
