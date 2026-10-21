"""CML Lab Builder: build, deploy and grade hands-on labs on Cisco Modeling Labs 2.9 (ENCOR is one track).

The Python package keeps its original name, encorlab: the installed program's boot loader loads app updates by that
name, so renaming it would break in-app updates for every existing install."""
import os as _os

__version__ = "2.1.0"
PRODUCT = "CML Lab Builder"

# Environment variables: CMLLAB_* (new) and ENCOR_* (before 2.1.0) are both accepted; CMLLAB_* wins. The code reads
# ENCOR_*, so the new names are copied over at import. The data folder variables are read with paths.env_get()
# instead: the boot loader in the installed program only knows ENCOR_DATA_DIR, and setting it here would make app
# updates land where that boot loader does not look.
for _k, _v in list(_os.environ.items()):
    if _k.startswith("CMLLAB_") and _k[7:] not in ("DATA_DIR", "SETTINGS_FILE"):
        _os.environ["ENCOR_" + _k[7:]] = _v
del _k, _v
