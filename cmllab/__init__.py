"""CML Lab Builder: build, deploy and grade hands-on labs on Cisco Modeling Labs 2.9 (ENCOR is one track).

Up to 2.1.0 the app was ENCOR Lab Builder and this package was called `encorlab`; 3.0.0 renamed everything."""
import os as _os

__version__ = "3.1.0"
PRODUCT = "CML Lab Builder"

# Environment variables are CMLLAB_*. The pre-3.0 names (ENCOR_*) still work: they are copied to the CMLLAB_* name at
# import unless that is set too (CMLLAB_* wins).
for _k, _v in list(_os.environ.items()):
    if _k.startswith("ENCOR_") and not _os.environ.get("CMLLAB_" + _k[6:]):
        _os.environ["CMLLAB_" + _k[6:]] = _v
del _k, _v
