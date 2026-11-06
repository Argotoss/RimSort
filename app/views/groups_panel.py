import json
from functools import partial
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.divider import is_divider_uuid
from app.models.metadata.metadata_structure import AboutXmlMod
from app.utils.json_utils import atomic_json_dump
from app.views.mods_panel import ModListWidget, ModsPanel


class GroupTree(QTreeWidget):
    assigned = Signal(list, str)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        target = self.itemAt(event.position().toPoint())
        if target is None:
            event.ignore()
            return
        parent = target.parent() or target
        group = str(parent.data(0, Qt.ItemDataRole.UserRole) or "")
        ids = [
            str(item.data(0, Qt.ItemDataRole.UserRole))
            for item in self.selectedItems()
            if item.parent() is not None
        ]
        if ids:
            QTimer.singleShot(0, partial(self.assigned.emit, ids, group))
            event.acceptProposedAction()
        else:
            event.ignore()


class GroupsPanel(QWidget):
    selected = Signal(str)
    toggled = Signal(str)

    def __init__(self, mods_panel: ModsPanel) -> None:
        super().__init__()
        self.mods_panel = mods_panel
        self.storage_path: Path | None = None
        self.storage_stamp: tuple[int, int] | None = None
        self.groups: list[dict[str, str]] = []
        self.members: dict[str, str] = {}
        self.collapsed: set[str] = set()
        self.load_failed = False
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems([self.tr("Enabled"), self.tr("All"), self.tr("Disabled")])
        self.mode.setToolTip(self.tr("Choose which mods appear in groups"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search groups, mods or package IDs…"))
        self.search.setClearButtonEnabled(True)
        self.colors = QCheckBox(self.tr("Group colors"))
        self.colors.setChecked(True)
        create = QPushButton(self.tr("New group"))
        toolbar.addWidget(self.mode)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.colors)
        toolbar.addWidget(create)
        layout.addLayout(toolbar)
        self.tree = GroupTree()
        self.tree.setHeaderLabels([self.tr("Group / mod"), self.tr("Status")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setColumnWidth(0, 470)
        layout.addWidget(self.tree)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.colors.toggled.connect(self._save_preferences)
        create.clicked.connect(self.create_group)
        self.tree.itemSelectionChanged.connect(self._select)
        self.tree.itemDoubleClicked.connect(self._toggle)
        self.tree.itemCollapsed.connect(self._collapse)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.assigned.connect(self.assign)
        for source in self.sources():
            source.list_update_signal.connect(self.schedule_refresh)

    def sources(self) -> tuple[ModListWidget, ModListWidget]:
        return (
            self.mods_panel.active_mods_list,
            self.mods_panel.inactive_mods_list,
        )

    def schedule_refresh(self, _list_type: str = "") -> None:
        self.refresh_timer.start(50)

    def _load(self) -> None:
        path = Path(self.mods_panel.settings.current_instance_path) / "groups.json"
        stamp = self._file_stamp(path)
        if path == self.storage_path and stamp == self.storage_stamp:
            return
        self.storage_path = path
        self.storage_stamp = stamp
        self.groups, self.members, self.collapsed = [], {}, set()
        self.load_failed = False
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            groups = data["groups"]
            members = data["members"]
            if not isinstance(groups, list) or not isinstance(members, dict):
                raise TypeError("Invalid groups document")
            names = [g["name"] for g in groups]
            if any(not isinstance(n, str) or not n.strip() for n in names):
                raise ValueError("Invalid group name")
            if len(set(names)) != len(names):
                raise ValueError("Duplicate group names")
            self.groups = groups
            self.members = {str(k).lower(): str(v) for k, v in members.items()}
            self.collapsed = set(data.get("collapsed", []))
            self.colors.blockSignals(True)
            self.colors.setChecked(bool(data.get("colors", True)))
            self.colors.blockSignals(False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.load_failed = True
            QMessageBox.warning(self, self.tr("Cannot read groups"), str(error))

    @staticmethod
    def _file_stamp(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def save(self) -> None:
        if self.storage_path is None or self.load_failed:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_dump(
                {
                    "groups": self.groups,
                    "members": self.members,
                    "collapsed": sorted(self.collapsed),
                    "colors": self.colors.isChecked(),
                },
                str(self.storage_path),
                indent=2,
            )
            self.storage_stamp = self._file_stamp(self.storage_path)
        except OSError as error:
            QMessageBox.warning(self, self.tr("Groups were not saved"), str(error))

    def _save_preferences(self) -> None:
        self.save()
        self.refresh()

    def refresh(self) -> None:
        self._load()
        selected = self.tree.currentItem()
        selected_id = (
            selected.data(0, Qt.ItemDataRole.UserRole)
            if selected is not None and selected.parent() is not None
            else None
        )
        self.tree.blockSignals(True)
        self.tree.clear()
        parents: dict[str, QTreeWidgetItem] = {}
        for group in [*self.groups, {"name": "", "color": ""}]:
            name = group["name"]
            parent = QTreeWidgetItem([name or self.tr("Ungrouped")])
            parent.setData(0, Qt.ItemDataRole.UserRole, name)
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            color = QColor(group.get("color", ""))
            if self.colors.isChecked() and color.isValid():
                color.setAlpha(45)
                for column in range(2):
                    parent.setBackground(column, QBrush(color))
            self.tree.addTopLevelItem(parent)
            parents[name] = parent

        needle = self.search.text().casefold().strip()
        for enabled, source in zip((True, False), self.sources()):
            if (self.mode.currentIndex() == 0 and not enabled) or (
                self.mode.currentIndex() == 2 and enabled
            ):
                continue
            for uuid in source.paths:
                if is_divider_uuid(uuid):
                    continue
                mod = self.mods_panel.metadata_controller.get_mod(uuid)
                if not isinstance(mod, AboutXmlMod):
                    continue
                package_id = str(mod.package_id).lower()
                group_name = self.members.get(package_id, "")
                parent = parents.get(group_name, parents[""])
                if needle and needle not in (
                    f"{mod.name} {package_id} {group_name}".casefold()
                ):
                    continue
                child = QTreeWidgetItem(
                    [
                        str(mod.name),
                        self.tr("Enabled") if enabled else self.tr("Disabled"),
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, package_id)
                child.setData(0, Qt.ItemDataRole.UserRole + 1, uuid)
                child.setToolTip(0, package_id)
                child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
                parent.addChild(child)
                if package_id == selected_id:
                    self.tree.setCurrentItem(child)
        for name, parent in parents.items():
            parent.sortChildren(0, Qt.SortOrder.AscendingOrder)
            parent.setText(0, f"{name or self.tr('Ungrouped')} ({parent.childCount()})")
            parent.setExpanded(bool(needle) or name not in self.collapsed)
        self.tree.blockSignals(False)

    def _select(self) -> None:
        item = self.tree.currentItem()
        if item is not None and item.parent() is not None:
            self.selected.emit(str(item.data(0, Qt.ItemDataRole.UserRole + 1)))

    def _toggle(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.parent() is not None:
            self.toggled.emit(str(item.data(0, Qt.ItemDataRole.UserRole + 1)))
            self.schedule_refresh()

    def _collapse(self, item: QTreeWidgetItem) -> None:
        self.collapsed.add(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
        self.save()

    def _expand(self, item: QTreeWidgetItem) -> None:
        self.collapsed.discard(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
        self.save()

    def create_group(self) -> None:
        name, accepted = QInputDialog.getText(
            self, self.tr("New group"), self.tr("Group name")
        )
        if accepted:
            name = name.strip()
            if name and name not in {g["name"] for g in self.groups}:
                self.groups.append({"name": name, "color": ""})
                self.save()
                self.refresh()

    def assign(self, ids: list[str], group: str) -> None:
        for package_id in ids:
            if group:
                self.members[package_id.lower()] = group
            else:
                self.members.pop(package_id.lower(), None)
        self.save()
        self.refresh()

    def _menu(self, point: QPoint) -> None:
        item = self.tree.itemAt(point)
        menu = QMenu(self)
        menu.addAction(self.tr("New group"), self.create_group)
        if item is not None and item.parent() is not None:
            ids = [
                str(i.data(0, Qt.ItemDataRole.UserRole))
                for i in self.tree.selectedItems()
                if i.parent() is not None
            ]
            if not ids:
                ids = [str(item.data(0, Qt.ItemDataRole.UserRole))]
            submenu = menu.addMenu(self.tr("Move to group"))
            for group in self.groups:
                name = group["name"]
                submenu.addAction(name, partial(self.assign, ids, name))
            submenu.addAction(self.tr("Ungrouped"), lambda: self.assign(ids, ""))
        elif item is not None:
            name = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if name:
                menu.addAction(self.tr("Rename group"), lambda: self._rename(name))
                menu.addAction(self.tr("Group color…"), lambda: self._color(name))
                menu.addAction(
                    self.tr("Remove color"), lambda: self._set_color(name, "")
                )
                menu.addAction(self.tr("Remove group"), lambda: self._remove(name))
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def _rename(self, name: str) -> None:
        new, accepted = QInputDialog.getText(
            self, self.tr("Rename group"), self.tr("Group name"), text=name
        )
        new = new.strip()
        if not accepted or not new or new == name:
            return
        if new in {g["name"] for g in self.groups}:
            return
        next(g for g in self.groups if g["name"] == name)["name"] = new
        self.members = {pid: new if n == name else n for pid, n in self.members.items()}
        if name in self.collapsed:
            self.collapsed.remove(name)
            self.collapsed.add(new)
        self.save()
        self.refresh()

    def _color(self, name: str) -> None:
        color = QColorDialog.getColor(QColor("#8298ac"), self, self.tr("Group color"))
        if color.isValid():
            color.setHsl(color.hslHue(), min(color.hslSaturation(), 95), 160)
            self._set_color(name, color.name())

    def _set_color(self, name: str, color: str) -> None:
        next(g for g in self.groups if g["name"] == name)["color"] = color
        self.save()
        self.refresh()

    def _remove(self, name: str) -> None:
        self.groups = [g for g in self.groups if g["name"] != name]
        self.members = {pid: n for pid, n in self.members.items() if n != name}
        self.collapsed.discard(name)
        self.save()
        self.refresh()
