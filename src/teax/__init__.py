"""teax - Gitea CLI companion for tea feature gaps."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("teax")
except PackageNotFoundError:
    # Package not installed (running from source)
    __version__ = "0.0.0.dev"
