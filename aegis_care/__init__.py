"""AEGIS-Care: a privacy-bounded memory recompiler for clinical AI agents.

Importing the package loads .env first, so that every entry point - the CLI,
uvicorn, the test suite, a bare `import aegis_care` - sees the same settings.
Modules that read configuration at import time (the assistant reads its model
name and token caps that way) therefore cannot observe a half-loaded
environment.
"""
from .config import load_dotenv as _load_dotenv

_load_dotenv()

__all__ = ["__version__"]
__version__ = "5.0.0"
