"""Independent async client for Petlibro's unofficial cloud API.

Endpoint paths and request fields were learned from the community Home Assistant
integration (jjjonesjr33/petlibro, GPL-3.0). No code was copied from it.
"""

from .client import PetlibroAuthError, PetlibroClient, PetlibroError

__all__ = ["PetlibroAuthError", "PetlibroClient", "PetlibroError"]
