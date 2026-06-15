"""
Cython build configuration for pypsx.

Compiles all implementation modules into platform-specific binary extensions
(.pyd on Windows, .so on Linux/macOS). __init__.py, models.py, and constants.py
are intentionally excluded so they remain as plain-text Python re-exporters.

CleanSourceBuildExt removes the original .py source files from the build/lib
tree after compilation so they are never bundled into the final wheel.
"""
import os
import glob
from setuptools import setup, Extension, find_packages
from setuptools.command.build_ext import build_ext as _build_ext
from Cython.Build import cythonize

# Stems that must stay as plain Python (pickling, isinstance, re-exports)
EXCLUDE_STEMS = {"__init__", "constants", "models"}

# Folders to skip entirely
EXCLUDE_DIRS = {"build", "dist", "tests", "__pycache__", ".git"}


class CleanSourceBuildExt(_build_ext):
    """After Cython compiles .py → .pyd/.so, delete the .py source files
    from the build/lib tree so they are never bundled into the wheel."""

    def run(self):
        super().run()
        build_lib = self.build_lib
        for root, dirs, files in os.walk(build_lib):
            for file in files:
                if file.endswith(".py"):
                    stem = os.path.splitext(file)[0]
                    if stem not in EXCLUDE_STEMS:
                        os.remove(os.path.join(root, file))


def collect_extensions(pkg_root: str):
    extensions = []
    for path in glob.glob(f"{pkg_root}/**/*.py", recursive=True):
        norm = path.replace("\\", "/")

        parts = norm.split("/")
        if any(p in EXCLUDE_DIRS for p in parts):
            continue

        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in EXCLUDE_STEMS:
            continue

        # Convert path to dotted module name (e.g. pypsx/core/fetchers.py -> pypsx.core.fetchers)
        module = norm.replace("/", ".")[:-3]
        extensions.append(
            Extension(
                module,
                [path],
                extra_compile_args=["/O2"] if os.name == "nt" else ["-O2"],
            )
        )
    return extensions


extensions = collect_extensions("pypsx")

setup(
    packages=find_packages(
        exclude=["build*", "dist*", "tests*", "*.egg-info*"]
    ),
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "binding": True,
            "embedsignature": True,
        },
        build_dir="build",
        annotate=False,
        nthreads=4,
    ),
    package_data={"": ["*.pyi", "py.typed"]},
    zip_safe=False,
    cmdclass={"build_ext": CleanSourceBuildExt},
)
