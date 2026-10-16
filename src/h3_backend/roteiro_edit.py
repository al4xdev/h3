"""Compatibility shim; canonical module is h3_backend.roteiro.edit."""

from .roteiro.edit import *
from .roteiro.edit import (  # noqa: F401
    EditGenerate,
    EditRecord,
    EditRequest,
    Revision,
    RoteiroEdit,
    assert_edit_available,
    router,
)
