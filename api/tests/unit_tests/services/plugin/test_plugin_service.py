from unittest.mock import MagicMock, patch

import pytest

from core.plugin.entities.plugin import PluginInstallationSource
from services.errors.plugin import PluginInstallationForbiddenError
from services.feature_service import PluginInstallationScope
from services.plugin.plugin_service import PluginService

MODULE = "services.plugin.plugin_service"


def _make_features(
    restrict_to_marketplace: bool = False,
    scope: PluginInstallationScope = PluginInstallationScope.ALL,
) -> MagicMock:
    features = MagicMock()
    features.plugin_installation_permission.restrict_to_marketplace_only = restrict_to_marketplace
    features.plugin_installation_permission.plugin_installation_scope = scope
    return features


class TestInstallFromLocalPkg:
    @patch(f"{MODULE}.FeatureService")
    @patch(f"{MODULE}.PluginInstaller")
    def test_fresh_install_when_no_existing_plugin(self, mock_installer_cls, mock_fs):
        mock_fs.get_system_features.return_value = _make_features()
        installer = mock_installer_cls.return_value
        decode_resp = MagicMock()
        decode_resp.verification = None
        decode_resp.manifest.author = "langgenius"
        decode_resp.manifest.name = "openai"
        installer.decode_plugin_from_identifier.return_value = decode_resp
        installer.list_plugins.return_value = []
        installer.install_from_identifiers.return_value = MagicMock()

        result = PluginService.install_from_local_pkg("t1", ["langgenius/openai/0.0.2"])

        installer.install_from_identifiers.assert_called_once()
        call_args = installer.install_from_identifiers.call_args[0]
        assert call_args[1] == ["langgenius/openai/0.0.2"]
        assert call_args[3] == [{}]
        installer.upgrade_plugin.assert_not_called()
        assert result is not None

    @patch(f"{MODULE}.FeatureService")
    @patch(f"{MODULE}.PluginInstaller")
    def test_upgrade_when_same_plugin_id_already_installed(self, mock_installer_cls, mock_fs):
        mock_fs.get_system_features.return_value = _make_features()
        installer = mock_installer_cls.return_value
        decode_resp = MagicMock()
        decode_resp.verification = None
        decode_resp.manifest.author = "langgenius"
        decode_resp.manifest.name = "openai"
        installer.decode_plugin_from_identifier.return_value = decode_resp

        existing_plugin = MagicMock()
        existing_plugin.plugin_id = "langgenius/openai"
        existing_plugin.plugin_unique_identifier = "langgenius/openai/0.0.1"
        installer.list_plugins.return_value = [existing_plugin]
        installer.upgrade_plugin.return_value = MagicMock()

        result = PluginService.install_from_local_pkg("t1", ["langgenius/openai/0.0.2"])

        installer.upgrade_plugin.assert_called_once_with(
            "t1",
            "langgenius/openai/0.0.1",
            "langgenius/openai/0.0.2",
            PluginInstallationSource.Package,
            {"plugin_unique_identifier": "langgenius/openai/0.0.2"},
        )
        installer.install_from_identifiers.assert_not_called()
        assert result is None

    @patch(f"{MODULE}.FeatureService")
    @patch(f"{MODULE}.PluginInstaller")
    def test_fresh_install_when_same_identifier_already_installed(self, mock_installer_cls, mock_fs):
        mock_fs.get_system_features.return_value = _make_features()
        installer = mock_installer_cls.return_value
        decode_resp = MagicMock()
        decode_resp.verification = None
        decode_resp.manifest.author = "langgenius"
        decode_resp.manifest.name = "openai"
        installer.decode_plugin_from_identifier.return_value = decode_resp

        existing_plugin = MagicMock()
        existing_plugin.plugin_id = "langgenius/openai"
        existing_plugin.plugin_unique_identifier = "langgenius/openai/0.0.1"
        installer.list_plugins.return_value = [existing_plugin]
        installer.install_from_identifiers.return_value = MagicMock()

        result = PluginService.install_from_local_pkg("t1", ["langgenius/openai/0.0.1"])

        installer.upgrade_plugin.assert_not_called()
        installer.install_from_identifiers.assert_called_once()
        call_args = installer.install_from_identifiers.call_args[0]
        assert call_args[1] == ["langgenius/openai/0.0.1"]
        assert result is not None

    @patch(f"{MODULE}.FeatureService")
    @patch(f"{MODULE}.PluginInstaller")
    def test_mixed_install_and_upgrade(self, mock_installer_cls, mock_fs):
        mock_fs.get_system_features.return_value = _make_features()
        installer = mock_installer_cls.return_value

        decode_resp_openai = MagicMock()
        decode_resp_openai.verification = None
        decode_resp_openai.manifest.author = "langgenius"
        decode_resp_openai.manifest.name = "openai"

        decode_resp_anthropic = MagicMock()
        decode_resp_anthropic.verification = None
        decode_resp_anthropic.manifest.author = "langgenius"
        decode_resp_anthropic.manifest.name = "anthropic"

        installer.decode_plugin_from_identifier.side_effect = [
            decode_resp_openai,
            decode_resp_anthropic,
        ]

        existing_plugin = MagicMock()
        existing_plugin.plugin_id = "langgenius/openai"
        existing_plugin.plugin_unique_identifier = "langgenius/openai/0.0.1"
        installer.list_plugins.return_value = [existing_plugin]
        installer.upgrade_plugin.return_value = MagicMock()
        installer.install_from_identifiers.return_value = MagicMock()

        result = PluginService.install_from_local_pkg(
            "t1",
            ["langgenius/openai/0.0.2", "langgenius/anthropic/0.0.1"],
        )

        installer.upgrade_plugin.assert_called_once_with(
            "t1",
            "langgenius/openai/0.0.1",
            "langgenius/openai/0.0.2",
            PluginInstallationSource.Package,
            {"plugin_unique_identifier": "langgenius/openai/0.0.2"},
        )
        installer.install_from_identifiers.assert_called_once()
        call_args = installer.install_from_identifiers.call_args[0]
        assert call_args[1] == ["langgenius/anthropic/0.0.1"]
        assert result is not None

    @patch(f"{MODULE}.FeatureService")
    @patch(f"{MODULE}.PluginInstaller")
    def test_raises_when_marketplace_only_restricted(self, mock_installer_cls, mock_fs):
        mock_fs.get_system_features.return_value = _make_features(restrict_to_marketplace=True)

        with pytest.raises(PluginInstallationForbiddenError):
            PluginService.install_from_local_pkg("t1", ["langgenius/openai/0.0.1"])

    @patch(f"{MODULE}.FeatureService")
    @patch(f"{MODULE}.PluginInstaller")
    def test_all_plugins_upgraded_returns_none(self, mock_installer_cls, mock_fs):
        mock_fs.get_system_features.return_value = _make_features()
        installer = mock_installer_cls.return_value

        decode_resp = MagicMock()
        decode_resp.verification = None
        decode_resp.manifest.author = "langgenius"
        decode_resp.manifest.name = "openai"
        installer.decode_plugin_from_identifier.return_value = decode_resp

        existing_plugin = MagicMock()
        existing_plugin.plugin_id = "langgenius/openai"
        existing_plugin.plugin_unique_identifier = "langgenius/openai/0.0.1"
        installer.list_plugins.return_value = [existing_plugin]
        installer.upgrade_plugin.return_value = MagicMock()

        result = PluginService.install_from_local_pkg("t1", ["langgenius/openai/0.0.2"])

        installer.upgrade_plugin.assert_called_once()
        installer.install_from_identifiers.assert_not_called()
        assert result is None


class TestUninstall:
    @patch(f"{MODULE}.PluginInstaller")
    def test_direct_uninstall_when_plugin_not_found(self, mock_installer_cls):
        installer = mock_installer_cls.return_value
        installer.list_plugins.return_value = []
        installer.uninstall.return_value = True

        result = PluginService.uninstall("t1", "install-1")

        assert result is True
        installer.uninstall.assert_called_once_with("t1", "install-1")

    @patch(f"{MODULE}.db")
    @patch(f"{MODULE}.dify_config")
    @patch(f"{MODULE}.PluginInstaller")
    def test_delegates_to_daemon_uninstall_when_plugin_found(self, mock_installer_cls, mock_config, mock_db):
        mock_config.ENTERPRISE_ENABLED = False
        installer = mock_installer_cls.return_value
        plugin = MagicMock()
        plugin.installation_id = "install-1"
        plugin.plugin_id = "org/myplugin"
        plugin.plugin_unique_identifier = "org/myplugin/0.0.1"
        installer.list_plugins.return_value = [plugin]
        installer.uninstall.return_value = True

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.scalars.return_value.all.return_value = []
        mock_db.engine = MagicMock()
        mock_db.engine.__enter__ = MagicMock(return_value=mock_db.engine)
        mock_db.engine.__exit__ = MagicMock(return_value=False)

        with patch(f"{MODULE}.Session", return_value=mock_session):
            result = PluginService.uninstall("t1", "install-1")

        assert result is True
        installer.uninstall.assert_called_once_with("t1", "install-1")
