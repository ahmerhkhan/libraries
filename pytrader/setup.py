import glob
import os
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from Cython.Build import cythonize


_SHIP_AS_PY = {
    # Backend-only engine — excluded from Cython, ships as plain .py
    "live_engine",
}


class build_py(_build_py):
    """Exclude .py source files except those that couldn't be Cythonized."""
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [(pkg, mod, path) for pkg, mod, path in modules if mod in _SHIP_AS_PY]


_EXCLUDE = {
    # Backend-only engine — uses requests/lambda **kwargs patterns incompatible with Cython
    "pytrader/trader_core/execution/live_engine.py",
}
source_files = sorted(
    f for f in glob.glob("pytrader/**/*.py", recursive=True)
    if f.replace("\\", "/") not in _EXCLUDE
)

setup(
    ext_modules=cythonize(
        source_files,
        compiler_directives={"language_level": "3", "embedsignature": False},
        nthreads=os.cpu_count() or 1,
    ),
    cmdclass={"build_py": build_py},
)
