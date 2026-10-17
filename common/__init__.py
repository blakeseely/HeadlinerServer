# Make `import common` work no matter which directory a build script runs from.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
