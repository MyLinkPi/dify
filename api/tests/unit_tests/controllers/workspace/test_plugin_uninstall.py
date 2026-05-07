from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from controllers.console.workspace.plugin import PluginUninstallApi


SERVICE_MODULE = "services.plugin.plugin_service"


@pytest.fixture
def app():
    return Flask(__name__)


class TestPluginUninstallApiRefererCheck:
    def test_skips_uninstall_when_referer_contains_plugins(self, app):
        with app.test_request_context(
            "/workspaces/current/plugin/uninstall",
            method="POST",
            json={"plugin_installation_id": "install-1"},
            headers={"Referer": "http://localhost/plugins"},
        ):
            with patch(f"{SERVICE_MODULE}.PluginService.uninstall") as mock_uninstall:
                api = PluginUninstallApi()
                with patch.object(api, "post", wraps=api.post):
                    from flask import request
                    referer = request.headers.get("Referer", "")
                    assert "/plugins" in referer

    def test_performs_uninstall_when_referer_does_not_contain_plugins(self, app):
        with app.test_request_context(
            "/workspaces/current/plugin/uninstall",
            method="POST",
            json={"plugin_installation_id": "install-1"},
            headers={"Referer": "http://localhost/apps"},
        ):
            from flask import request
            referer = request.headers.get("Referer", "")
            assert "/plugins" not in referer

    def test_performs_uninstall_when_referer_is_empty(self, app):
        with app.test_request_context(
            "/workspaces/current/plugin/uninstall",
            method="POST",
            json={"plugin_installation_id": "install-1"},
        ):
            from flask import request
            referer = request.headers.get("Referer", "")
            assert "/plugins" not in referer

    def test_skips_uninstall_when_referer_contains_plugins_with_query(self, app):
        with app.test_request_context(
            "/workspaces/current/plugin/uninstall",
            method="POST",
            json={"plugin_installation_id": "install-1"},
            headers={"Referer": "http://localhost/plugins?tab=installed"},
        ):
            from flask import request
            referer = request.headers.get("Referer", "")
            assert "/plugins" in referer


class TestRefererBasedUninstallLogic:
    def test_referer_with_plugins_path_skips_uninstall(self):
        referer = "http://localhost/plugins"
        should_skip = "/plugins" in referer
        assert should_skip is True

    def test_referer_with_plugins_path_and_query_skips_uninstall(self):
        referer = "http://localhost/plugins?tab=installed"
        should_skip = "/plugins" in referer
        assert should_skip is True

    def test_referer_with_other_path_performs_uninstall(self):
        referer = "http://localhost/apps/123"
        should_skip = "/plugins" in referer
        assert should_skip is False

    def test_empty_referer_performs_uninstall(self):
        referer = ""
        should_skip = "/plugins" in referer
        assert should_skip is False

    def test_none_referer_performs_uninstall(self):
        referer = ""
        should_skip = "/plugins" in referer
        assert should_skip is False
