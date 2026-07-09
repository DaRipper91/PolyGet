"""Main Terminal User Interface (TUI) for the package upgrader."""

import asyncio
import shutil
from typing import Any
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, ListView, ListItem, Label, RichLog, ProgressBar, Input, Button
from textual.containers import Horizontal, Vertical
from app.core.manager import discover_managers, PackageManager


class HelpModal(ModalScreen[None]):
    """A beautiful help overlay modal dialog showing all keybindings."""

    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("q", "dismiss", "Dismiss"),
        ("enter", "dismiss", "Dismiss"),
        ("space", "dismiss", "Dismiss"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the help modal widgets."""
        with Vertical(id="help-dialog"):
            yield Label("ℹ️ [bold #c084fc]Keyboard Shortcuts[/]")
            
            help_text = (
                "[bold #a78bfa]q[/]      - Quit the application\n"
                "[bold #a78bfa]Space[/]  - Toggle selection of the highlighted manager\n"
                "[bold #a78bfa]r[/]      - Rescan the system for package managers\n"
                "[bold #a78bfa]u[/]      - Upgrade selected package managers\n"
                "[bold #a78bfa]a[/]      - Upgrade all discovered package managers\n"
                "[bold #a78bfa]? / h[/]  - Show this help menu\n\n"
                "Press [bold #8b5cf6]ESC[/], [bold #8b5cf6]Enter[/], or [bold #8b5cf6]Space[/] to return to the app."
            )
            yield Label(help_text, id="help-text")
            with Horizontal(id="help-buttons"):
                yield Button("Close", variant="primary", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "close-btn":
            self.dismiss()


class PasswordModal(ModalScreen[str | None]):
    """A secure modal dialog to prompt the user for a sudo password."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the password modal widgets."""
        with Vertical(id="password-dialog"):
            yield Label("🔒 [bold #c084fc]Sudo Password Required[/]")
            yield Label("The upgrade command requires administrator privileges.\n"
                        "Please enter your password below:")
            yield Input(placeholder="Password", password=True, id="password-input")
            with Horizontal(id="password-buttons"):
                yield Button("Submit", variant="primary", id="submit-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        """Focus the password input field when mounted."""
        self.query_one("#password-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "submit-btn":
            password = self.query_one("#password-input", Input).value
            self.dismiss(password)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission events."""
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        """Cancel the dialog and dismiss with None."""
        self.dismiss(None)


class PolyUpApp(App[None]):
    """Ultimate Package PolyUp TUI Application."""

    TITLE = "PolyUp"
    CSS_PATH = "tui.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("space", "toggle_select", "Toggle Select"),
        ("r", "rescan_managers", "Rescan"),
        ("u", "upgrade_selected", "Upgrade Selected"),
        ("a", "upgrade_all", "Upgrade All"),
        ("question_mark", "show_help", "Help"),
        ("h", "show_help", "Help"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the PolyUpApp, discover available managers, and set up state."""
        super().__init__(**kwargs)
        self.managers: list[PackageManager] = discover_managers()
        # Track selected managers for upgrading
        self.selected_managers: set[str] = set()
        # Track which managers are currently being checked/scanned
        self.checking_managers: set[str] = set()
        # Outdated package cache, dynamically populated
        self.updates_cache: dict[str, list[dict[str, Any]]] = {}

    def compose(self) -> ComposeResult:
        """Compose the TUI layout widgets.

        Yields:
            ComposeResult: The sub-widgets that form the TUI.
        """
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label(" 📦 Managers", classes="title-label")
                yield ListView(id="manager-list")
            with Vertical(id="main-panel"):
                with Vertical(id="details-panel"):
                    yield Label(" 🔍 Details", classes="title-label")
                    yield Label("Select a package manager to view details...", id="details-text")
                    yield Label("", id="details-content")
                with Vertical(id="terminal-panel"):
                    yield Label(" ⚡ Live Progress", classes="title-label")
                    yield ProgressBar(total=100, show_bar=True, show_eta=False)
                    yield RichLog(id="terminal-log", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the manager list in the sidebar and start parallel scans."""
        self._update_header_status()
        self.notify("Scanning system for package managers...", title="Upgrader", severity="info", timeout=3)
        list_view = self.query_one("#manager-list", ListView)
        if not self.managers:
            list_view.append(ListItem(Label("No managers detected")))
        else:
            for mgr in self.managers:
                self.checking_managers.add(mgr.name)
                label_text = self._get_manager_label(mgr)
                list_view.append(ListItem(Label(label_text), name=mgr.name))
                # Spawn background worker to check updates
                self.run_worker(self._scan_manager(mgr), name=f"scan-{mgr.name}")

    async def _scan_manager(self, mgr: PackageManager) -> None:
        """Scan a single package manager for updates in the background."""
        try:
            updates = await mgr.check_updates()
        except Exception:
            updates = []

        self.updates_cache[mgr.name] = updates
        if updates:
            self.selected_managers.add(mgr.name)
            self.notify(f"Scan complete: {mgr.name} ({len(updates)} updates)", title="Upgrader", severity="warning", timeout=3)
        else:
            self.notify(f"Scan complete: {mgr.name} (Up to date)", title="Upgrader", severity="info", timeout=3)

        if mgr.name in self.checking_managers:
            self.checking_managers.remove(mgr.name)

        # Update the list item label in the sidebar
        list_view = self.query_one("#manager-list", ListView)
        for item in list_view.children:
            if item.name == mgr.name:
                label = item.query_one(Label)
                label.update(self._get_manager_label(mgr))
                break

        self._update_header_status()

        # Trigger details panel refresh if this manager is currently highlighted
        highlighted_item = list_view.highlighted_child
        if highlighted_item and highlighted_item.name == mgr.name:
            self.on_list_view_highlighted(ListView.Highlighted(list_view, highlighted_item))

    def _get_manager_label(self, mgr: PackageManager) -> str:
        """Generate the display label for a package manager in the list.

        Args:
            mgr: The package manager instance.

        Returns:
            str: The formatted label string.
        """
        selected_mark = "[x]" if mgr.name in self.selected_managers else "[ ]"
        if mgr.name in self.checking_managers:
            return f"{selected_mark} 🔄 {mgr.name} (Checking...)"

        updates = self.updates_cache.get(mgr.name, [])
        if updates:
            return f"{selected_mark} ⚠️ {mgr.name} ({len(updates)} updates)"
        else:
            return f"{selected_mark} ✅ {mgr.name} (Up to date)"

    def _update_header_status(self) -> None:
        """Update the application's subtitle with global status statistics."""
        active_count = len(self.managers)
        total_updates = sum(len(up) for up in self.updates_cache.values())
        self.sub_title = f"{active_count} active managers | {total_updates} total updates pending"

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle list item highlighting to update the details panel dynamically.

        Args:
            event: The highlight event from the ListView.
        """
        if event.item is None or event.item.name is None:
            return

        manager_name = event.item.name
        # Find the manager instance
        mgr = next((m for m in self.managers if m.name == manager_name), None)
        if not mgr:
            return

        # Update the title of details
        details_text = self.query_one("#details-text", Label)
        details_text.update(f"[bold #c084fc]{mgr.name} ({mgr.category} Package Manager)[/]")

        # Update details content
        checking = manager_name in self.checking_managers
        updates = self.updates_cache.get(mgr.name, [])
        
        if checking:
            status_style = "bold #38bdf8"
            status_text = "Checking for updates..."
        else:
            status_style = "bold #fbbf24" if updates else "bold #34d399"
            status_text = f"Outdated ({len(updates)} updates)" if updates else "Up to date"

        command_str = " ".join(mgr.get_upgrade_command())

        content = (
            f"Status: [{status_style}]{status_text}[/]\n"
            f"Upgrade Command: [bold #a78bfa]{command_str}[/]\n\n"
        )

        if checking:
            content += "Scanning for outdated packages in the background...\n"
        elif updates:
            content += "[bold]Outdated Packages:[/bold]\n"
            for pkg in updates:
                content += f"  • {pkg['name']} ({pkg['current']} -> {pkg['new']})\n"
        else:
            content += "All packages are currently up to date.\n"

        details_content = self.query_one("#details-content", Label)
        details_content.update(content)

    def action_toggle_select(self) -> None:
        """Toggle the selection state of the currently highlighted package manager."""
        list_view = self.query_one("#manager-list", ListView)
        highlighted_item = list_view.highlighted_child
        if not highlighted_item or highlighted_item.name is None:
            return

        manager_name = highlighted_item.name
        mgr = next((m for m in self.managers if m.name == manager_name), None)
        if not mgr:
            return

        if manager_name in self.selected_managers:
            self.selected_managers.remove(manager_name)
        else:
            self.selected_managers.add(manager_name)

        # Update label
        label = highlighted_item.query_one(Label)
        label.update(self._get_manager_label(mgr))

        # Trigger re-highlight to refresh the details view
        self.on_list_view_highlighted(ListView.Highlighted(list_view, highlighted_item))

    async def action_rescan_managers(self) -> None:
        """Rescan the system for package managers and add any newly discovered ones."""
        log = self.query_one("#terminal-log", RichLog)
        log.write("[bold #8b5cf6]🔄 Rescanning for package managers...[/]")

        discovered = discover_managers()
        existing_names = {mgr.name for mgr in self.managers}
        new_managers = [mgr for mgr in discovered if mgr.name not in existing_names]

        if not new_managers:
            log.write(" ✅ No new package managers found.")
            return

        log.write(f" 🎉 Found [bold green]{len(new_managers)}[/bold green] new package manager(s): {', '.join(mgr.name for mgr in new_managers)}")

        list_view = self.query_one("#manager-list", ListView)

        # If we previously had no managers detected, clear the placeholder
        if not self.managers:
            await list_view.clear()

        for mgr in new_managers:
            self.managers.append(mgr)
            self.checking_managers.add(mgr.name)
            label_text = self._get_manager_label(mgr)
            await list_view.append(ListItem(Label(label_text), name=mgr.name))
            # Spawn background worker to check updates for the new manager
            self.run_worker(self._scan_manager(mgr), name=f"scan-{mgr.name}")

        self._update_header_status()

    def action_show_help(self) -> None:
        """Show the keyboard shortcut help modal."""
        self.push_screen(HelpModal())

    async def _send_phone_notification(self, message: str) -> None:
        """Asynchronously send a phone notification via kdeconnect-cli if available."""
        if shutil.which("kdeconnect-cli") is None:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "kdeconnect-cli", "-a", "--id-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            device_ids = [line.strip().decode() for line in stdout.splitlines() if line.strip()]
            for dev_id in device_ids:
                await asyncio.create_subprocess_exec(
                    "kdeconnect-cli", "--device", dev_id, "--ping-msg", message,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
        except Exception:
            pass

    async def _upgrade_manager(self, mgr: PackageManager, password: str | None = "0") -> bool:
        """Run the upgrade command for a single package manager and stream output.

        Args:
            mgr: The package manager instance.
            password: The password to pipe to sudo if needed.

        Returns:
            bool: True if the upgrade succeeded, False otherwise.
        """
        log = self.query_one("#terminal-log", RichLog)
        cmd = list(mgr.get_upgrade_command())
        if not cmd:
            return False

        is_sudo = cmd[0] == "sudo"
        if is_sudo and "-S" not in cmd:
            cmd.insert(1, "-S")

        log.write(f" -> Upgrading {mgr.name} using command: [bold #a78bfa]{' '.join(cmd)}[/]...")
        await self._send_phone_notification(f"Starting upgrade for {mgr.name}...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            if is_sudo:
                pw = password if password is not None else ""
                proc.stdin.write(pw.encode() + b"\n")
                await proc.stdin.drain()
                proc.stdin.close()
            else:
                proc.stdin.close()

            async def read_stream(stream: asyncio.StreamReader) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    log.write(escape(line.decode(errors="ignore").rstrip()))

            await asyncio.gather(
                read_stream(proc.stdout),
                read_stream(proc.stderr),
                proc.wait()
            )

            if proc.returncode == 0:
                log.write(f" ✅ [bold green]{mgr.name} upgrade complete.[/bold green]")
                await self._send_phone_notification(f"✅ {mgr.name} upgrade complete.")
                return True
            else:
                log.write(f" ❌ [bold red]{mgr.name} upgrade failed with exit code {proc.returncode}.[/bold red]")
                await self._send_phone_notification(f"❌ {mgr.name} upgrade failed.")
                if is_sudo and password == "0":
                    loop = asyncio.get_running_loop()
                    fut = loop.create_future()

                    def modal_callback(user_password: str | None) -> None:
                        fut.set_result(user_password)

                    self.push_screen(PasswordModal(), modal_callback)
                    custom_password = await fut

                    if custom_password is not None:
                        log.write(f" 🔄 Retrying {mgr.name} upgrade with custom password...")
                        return await self._upgrade_manager(mgr, password=custom_password)
                return False
        except Exception as e:
            log.write(f" ❌ [bold red]Error running upgrade for {mgr.name}: {escape(str(e))}[/bold red]")
            await self._send_phone_notification(f"❌ {mgr.name} upgrade failed: {str(e)}")
            return False

    async def action_upgrade_selected(self) -> None:
        """Trigger the upgrade process for all selected package managers."""
        log = self.query_one("#terminal-log", RichLog)
        progress = self.query_one(ProgressBar)

        if not self.selected_managers:
            log.write("[bold yellow]⚠️ No package managers selected for upgrade.[/bold yellow]")
            return

        selected_instances = [m for m in self.managers if m.name in self.selected_managers]
        if not selected_instances:
            log.write("[bold yellow]⚠️ Selected package managers are not available.[/bold yellow]")
            return

        log.write(f"[bold #8b5cf6]⚡ Starting upgrade of selected managers: {escape(', '.join(self.selected_managers))}[/]")
        progress.progress = 0

        total_steps = len(selected_instances)
        for i, mgr in enumerate(selected_instances, 1):
            await self._upgrade_manager(mgr)
            progress.progress = int((i / total_steps) * 100)

        log.write("[bold green]🎉 All selected package managers upgraded successfully.[/bold green]")
        await self._send_phone_notification("🎉 All selected package upgrades completed.")

    async def action_upgrade_all(self) -> None:
        """Trigger the upgrade process for all discovered package managers."""
        log = self.query_one("#terminal-log", RichLog)
        progress = self.query_one(ProgressBar)

        if not self.managers:
            log.write("[bold yellow]⚠️ No package managers discovered on the system.[/bold yellow]")
            return

        log.write("[bold #8b5cf6]⚡ Starting full system upgrade of all package managers...[/]")
        progress.progress = 0

        total_steps = len(self.managers)
        for i, mgr in enumerate(self.managers, 1):
            await self._upgrade_manager(mgr)
            progress.progress = int((i / total_steps) * 100)

        log.write("[bold green]🎉 Full system upgrade completed successfully.[/bold green]")
        await self._send_phone_notification("🎉 Full system upgrades completed.")
