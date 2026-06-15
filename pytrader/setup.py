import glob
import os
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from Cython.Build import cythonize


class build_py(_build_py):
    """Exclude .py source files from the wheel — everything is compiled to C extensions."""
    def find_package_modules(self, package, package_dir):
        return []


source_files = sorted(glob.glob("pytrader/**/*.py", recursive=True))

setup(
    ext_modules=cythonize(
        source_files,
        compiler_directives={"language_level": "3", "embedsignature": False},
        nthreads=os.cpu_count() or 1,
    ),
    cmdclass={"build_py": build_py},
)
