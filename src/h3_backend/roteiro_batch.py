"""Compatibility shim; canonical module is h3_backend.roteiro.batch."""

from .roteiro.batch import *
from .roteiro.batch import (  # noqa: F401
    RoteiroBatch,
    StartBatch,
    assert_batch_available,
    router,
)
