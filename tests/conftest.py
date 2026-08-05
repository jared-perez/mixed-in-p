"""Suite-wide isolation from the developer's own machine.

Everything the app persists — ``config.json``, ``library.db``, the analysis and
rename histories — hangs off ``src.utils.app_dirs.get_app_data_dir()``. Without
the fixture below, any test that reaches ``load_config()`` reads whatever the
developer last chose in Settings, and any test that boots a MainWindow opens
the *real* library.

That is not theoretical: three tests in ``tests/gui/test_player_header_layout``
passed here and failed on a fresh Windows checkout for exactly this reason, and
they would have failed on a clean Mac too. A suite that reads developer state
passes or fails on a machine's history rather than on its code.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path_factory, monkeypatch):
    """Point every persisted-data lookup at a throwaway directory.

    Patching ``get_app_data_dir`` on its defining module is enough to cover all
    of them: every caller imports it *inside* the function that needs it, so
    none has bound its own copy at import time.

    Deliberately not the test's own ``tmp_path`` — several tests scan that
    directory for audio files, and a ``library.db`` appearing in the middle of
    the fixtures under test is its own kind of surprise.

    Returned so a test can seed a config into it: build an ``AppConfig``, call
    ``save_config``, and construct the widget after. That is the honest way to
    give a widget a setting, because a widget that does
    ``from src.utils.config import load_config`` at module level has bound the
    function into its own namespace, and patching it on ``src.utils.config``
    would quietly do nothing.
    """
    data_dir = tmp_path_factory.mktemp("appdata")
    monkeypatch.setattr("src.utils.app_dirs.get_app_data_dir", lambda: data_dir)
    return data_dir
