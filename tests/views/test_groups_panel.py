from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from app.models.metadata.metadata_structure import AboutXmlMod, CaseInsensitiveStr
from app.models.settings import Settings
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.custom_list_widget_item_metadata import CustomListWidgetItemMetadata
from app.views.groups_panel import GroupsPanel
from app.views.main_content_panel import MainContent
from app.views.mods_panel import ModsPanel


def _root(groups: GroupsPanel, index: int = 0) -> QTreeWidgetItem:
    item = groups.tree.topLevelItem(index)
    assert item is not None
    return item


def _child(groups: GroupsPanel) -> QTreeWidgetItem:
    item = _root(groups).child(0)
    assert item is not None
    return item


@pytest.fixture
def groups(qtbot: QtBot, tmp_path: Path) -> GroupsPanel:
    settings = Settings()
    settings.current_instance_path = str(tmp_path)
    metadata = MagicMock()
    metadata.get_mod.side_effect = {
        "active-path": AboutXmlMod(
            name="Active Mod", package_id=CaseInsensitiveStr("example.active")
        ),
        "disabled-path": AboutXmlMod(
            name="Disabled Mod", package_id=CaseInsensitiveStr("example.disabled")
        ),
    }.get
    panel = ModsPanel(settings, metadata)
    qtbot.addWidget(panel)
    panel.active_mods_list.paths = ["active-path"]
    panel.inactive_mods_list.paths = ["disabled-path"]
    view = GroupsPanel(panel)
    qtbot.addWidget(view)
    view.refresh()
    return view


def test_modes_default_enabled_and_keep_order(groups: GroupsPanel) -> None:
    assert groups.mode.currentIndex() == 0
    root = _root(groups)
    assert root.childCount() == 1
    assert _child(groups).text(0) == "Active Mod"
    groups.mode.setCurrentIndex(1)
    assert _root(groups).childCount() == 2
    groups.mode.setCurrentIndex(2)
    assert _child(groups).text(0) == "Disabled Mod"
    assert groups.mods_panel.active_mods_list.paths == ["active-path"]
    assert groups.mods_panel.inactive_mods_list.paths == ["disabled-path"]


def test_membership_survives_restart_and_enabled_changes(groups: GroupsPanel) -> None:
    groups.groups = [{"name": "Bionics", "color": "#8298ac"}]
    groups.assign(["example.disabled"], "Bionics")
    groups.mods_panel.inactive_mods_list.paths.clear()
    groups.mods_panel.active_mods_list.paths.append("disabled-path")
    groups.refresh()
    assert _child(groups).text(0) == "Disabled Mod"
    groups.storage_path = None
    groups.refresh()
    assert groups.members["example.disabled"] == "Bionics"
    assert _root(groups).childCount() == 1
    assert _root(groups, 1).childCount() == 1


def test_select_and_double_click_use_original_mod_path(groups: GroupsPanel) -> None:
    selected: list[str] = []
    toggled: list[str] = []
    groups.selected.connect(selected.append)
    groups.toggled.connect(toggled.append)
    child = _child(groups)
    groups.tree.setCurrentItem(child)
    groups._toggle(child, 0)
    assert selected == ["active-path"]
    assert toggled == ["active-path"]
    groups._toggle(_root(groups), 0)
    assert len(toggled) == 1


def test_search_and_remove_group_preserve_mods(groups: GroupsPanel) -> None:
    groups.groups = [{"name": "Bionics", "color": ""}]
    groups.assign(["example.active"], "Bionics")
    groups.search.setText("bionics")
    assert _root(groups).childCount() == 1
    groups.search.clear()
    groups._remove("Bionics")
    assert _root(groups).childCount() == 1
    assert not groups.members
    assert groups.mods_panel.active_mods_list.paths == ["active-path"]


def test_broken_storage_is_not_overwritten(
    groups: GroupsPanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.views.groups_panel.QMessageBox.warning", MagicMock())
    assert groups.storage_path is not None
    groups.storage_path.write_text("broken JSON", encoding="utf-8")
    path = groups.storage_path
    groups.storage_path = None
    groups.refresh()
    groups.assign(["example.active"], "Bionics")
    assert path.read_text(encoding="utf-8") == "broken JSON"


def test_collapsed_state_and_color_preference_persist(groups: GroupsPanel) -> None:
    groups._collapse(_root(groups))
    groups.colors.setChecked(False)
    groups.storage_path = None
    groups.refresh()
    assert not _root(groups).isExpanded()
    assert not groups.colors.isChecked()
    assert _root(groups).data(0, Qt.ItemDataRole.UserRole) == ""


def test_external_group_edits_reload_without_restarting(groups: GroupsPanel) -> None:
    assert groups.storage_path is not None
    groups.storage_path.write_text(
        '{"groups":[{"name":"Biomes","color":""}],'
        '"members":{"example.active":"Biomes"}}',
        encoding="utf-8",
    )
    groups.refresh()
    assert _root(groups).text(0) == "Biomes (1)"
    assert _child(groups).text(0) == "Active Mod"


def test_double_click_moves_real_list_item_and_refreshes_filter(
    groups: GroupsPanel, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, inactive = groups.sources()
    active.paths.clear()
    inactive.paths.clear()
    for source in (active, inactive):
        source.check_widgets_visible = MagicMock()  # type: ignore[method-assign]
        monkeypatch.setattr(
            source,
            "recalculate_internal_errors_warnings",
            MagicMock(return_value=("", "", 0, 0)),
        )
    data = object.__new__(CustomListWidgetItemMetadata)
    data.path = "active-path"
    data.filtered = False
    data.invalid = False
    data.mod_tags = []
    item = CustomListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
    active.addItem(item)
    qtbot.waitUntil(lambda: active.paths == ["active-path"])
    receiver = SimpleNamespace(mods_panel=groups.mods_panel, groups_panel=groups)
    receiver._MainContent___get_relative_middle = lambda _source: 0
    controller = cast(MainContent, receiver)
    active.key_press_signal.connect(
        lambda key: MainContent._MainContent__handle_active_mod_key_press(  # type: ignore[attr-defined]
            controller, key
        )
    )
    inactive.key_press_signal.connect(
        lambda key: MainContent._MainContent__handle_inactive_mod_key_press(  # type: ignore[attr-defined]
            controller, key
        )
    )
    groups.toggled.connect(lambda uuid: MainContent._toggle_group_mod(controller, uuid))
    groups.refresh()
    groups._toggle(_child(groups), 0)
    qtbot.waitUntil(lambda: _root(groups).childCount() == 0)
    assert "active-path" not in active.paths
    assert "active-path" in inactive.paths
    groups.mode.setCurrentIndex(1)
    groups._toggle(_child(groups), 0)
    qtbot.waitUntil(lambda: _child(groups).text(1) == "Enabled")
    assert active.paths == ["active-path"]
