__version__ = "0.0.1"

# Imported here so the module is an attribute of the package, not merely
# importable from it. ERPNext's scorecard resolves a variable's path with
# __import__ on the first segment followed by getattr for the rest, and
# getattr does not trigger a submodule import.
from vendor_portal import scorecard  # noqa: F401