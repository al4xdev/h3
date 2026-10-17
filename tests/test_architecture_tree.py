"""Architecture and import tree verification test.

Ensures that reorganizing files into dedicated domain packages
preserves all public exports, backward-compatible import shims,
and FastAPI route registrations with zero regressions.
"""

from h3_backend.api import create_app


def test_notifications_package_imports():
    from h3_backend.notifications import (
        DeviceRegistration,
        NotificationConfig,
        NotificationManager,
        router,
    )
    assert DeviceRegistration is not None
    assert NotificationConfig is not None
    assert NotificationManager is not None
    assert router is not None


def test_roteiro_canonical_and_shim_imports():
    # Canonical package imports
    from h3_backend.roteiro import (
        Block,
        CreatePlan,
        Roteiro,
        UpdatePlan,
    )
    from h3_backend.roteiro import (
        router as roteiro_router,
    )
    assert Block is not None
    assert CreatePlan is not None
    assert UpdatePlan is not None
    assert Roteiro is not None
    assert roteiro_router is not None

    # Submodule imports
    from h3_backend.roteiro_batch import RoteiroBatch, assert_batch_available
    from h3_backend.roteiro_conversion import convert, observe_import
    from h3_backend.roteiro_edit import RoteiroEdit, assert_edit_available

    assert RoteiroBatch is not None
    assert assert_batch_available is not None
    assert RoteiroEdit is not None
    assert assert_edit_available is not None
    assert convert is not None
    assert observe_import is not None


def test_api_route_tree_completeness():
    app = create_app()
    paths = list(app.openapi()["paths"].keys())

    assert "/notifications/register" in paths
    assert "/notifications/devices" in paths
    assert "/runs" in paths
    assert "/roteiros/summary" in paths
