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
from app.core.coordinator import SubprocessCoordinator


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


_PKEXEC_NO_AGENT_MARKERS = (
    "authentication agent",
    "no session for cookie",
    "not authorized",
    "cannot determine the session",
)


def _looks_like_pkexec_no_agent_failure(stderr_text: str) -> bool:
    """Heuristic: pkexec failed because no polkit authentication agent is bound to
    this session (e.g. a bare terminal/SSH session with no desktop running), rather
    than because the privileged command itself failed for an unrelated reason. This
    is reasoned from documented polkit behavior, not verified against every polkit
    version — it deliberately requires a stderr marker rather than treating any
    nonzero pkexec exit as "needs a password," so real command failures (e.g. an
    unreachable mirror, a genuinely missing package) aren't masked as an auth issue.
    """
    lowered = stderr_text.lower()
    return any(marker in lowered for marker in _PKEXEC_NO_AGENT_MARKERS)


class PolyGetTuiApp(App[None]):
    """PolyGet TUI Application."""

    TITLE = "PolyGet"
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
        """Initialize the PolyGetTuiApp, discover available managers, and set up state."""
        super().__init__(**kwargs)
        self.managers: list[PackageManager] = discover_managers()
        # Track selected managers for upgrading
        self.selected_managers: set[str] = set()
        # Track which managers are currently being checked/scanned
        self.checking_managers: set[str] = set()
        # Outdated package cache, dynamically populated
        self.updates_cache: dict[str, list[dict[str, Any]]] = {}
        self.scan_errors: dict[str, str] = {}

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

    def on_unmount(self) -> None:
        """Terminate any still-running upgrade subprocesses when the app shuts down."""
        SubprocessCoordinator().terminate_all()

    async def _scan_manager(self, mgr: PackageManager) -> None:
        """Scan a single package manager for updates in the background."""
        error = None
        try:
            updates = await mgr.check_updates()
        except Exception as e:
            updates = []
            error = str(e)

        self.updates_cache[mgr.name] = updates
        if error:
            self.scan_errors[mgr.name] = error
            self.notify(
                f"Scan failed: {mgr.name} ({error})",
                title="Upgrader",
                severity="error",
                timeout=5,
            )
        elif updates:
            self.scan_errors.pop(mgr.name, None)
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
        if mgr.name in self.scan_errors:
            return f"{selected_mark} ❌ {mgr.name} (Scan failed)"
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
        scan_error = self.scan_errors.get(mgr.name)

        if scan_error:
            status_style = "bold #f38ba8"
            status_text = f"Scan failed: {scan_error}"
        elif checking:
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

        if scan_error:
            content += "The update check failed; no update status is available.\n"
        elif checking:
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

    async def _upgrade_manager(
        self,
        mgr: PackageManager,
        password: str | None = None,
        cmd_override: list[str] | None = None,
    ) -> bool:
        """Run the upgrade command for a single package manager and stream output.

        Args:
            mgr: The package manager instance.
            password: The password to pipe to sudo if needed. On the first call this
                is None, meaning no password has been supplied yet — stdin is closed
                without writing anything so sudo can use a cached credential or fail
                fast, rather than guessing. Only after that first attempt fails do we
                prompt the user and retry with what they typed (which may be "").
            cmd_override: Used internally to retry with a substituted `sudo` command
                after a pkexec no-auth-agent failure, instead of re-deriving
                `mgr.get_upgrade_command()` (which would just return `pkexec` again).

        Returns:
            bool: True if the upgrade succeeded, False otherwise.
        """
        log = self.query_one("#terminal-log", RichLog)
        cmd = list(cmd_override) if cmd_override is not None else list(mgr.get_upgrade_command())
        if not cmd:
            return False

        is_sudo = cmd[0] == "sudo"
        is_pkexec = cmd[0] == "pkexec"
        if is_sudo and "-S" not in cmd:
            cmd.insert(1, "-S")

        log.write(f" -> Upgrading {mgr.name} using command: [bold #a78bfa]{' '.join(cmd)}[/]...")
        await self._send_phone_notification(f"Starting upgrade for {mgr.name}...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True
            )
            coordinator = SubprocessCoordinator()
            coordinator.register(proc.pid)
            stderr_lines: list[str] = []
            try:
                if is_sudo and password is not None:
                    proc.stdin.write(password.encode() + b"\n")
                    await proc.stdin.drain()
                proc.stdin.close()

                async def read_stream(stream: asyncio.StreamReader, capture: list[str] | None = None) -> None:
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode(errors="ignore").rstrip()
                        if capture is not None:
                            capture.append(text)
                        log.write(escape(text))

                await asyncio.gather(
                    read_stream(proc.stdout),
                    read_stream(proc.stderr, stderr_lines),
                    proc.wait()
                )
            finally:
                coordinator.unregister(proc.pid)

            if proc.returncode == 0:
                log.write(f" ✅ [bold green]{mgr.name} upgrade complete.[/bold green]")
                await self._send_phone_notification(f"✅ {mgr.name} upgrade complete.")
                return True
            else:
                log.write(f" ❌ [bold red]{mgr.name} upgrade failed with exit code {proc.returncode}.[/bold red]")
                await self._send_phone_notification(f"❌ {mgr.name} upgrade failed.")

                needs_password_retry = (
                    password is None
                    and (
                        is_sudo
                        or (is_pkexec and _looks_like_pkexec_no_agent_failure("\n".join(stderr_lines)))
                    )
                )
                if needs_password_retry:
                    if is_pkexec:
                        log.write(
                            " ⚠️ No polkit authentication agent is bound to this session "
                            "(common over SSH or in a minimal terminal) — falling back to sudo."
                        )
                    loop = asyncio.get_running_loop()
                    fut = loop.create_future()

                    def modal_callback(user_password: str | None) -> None:
                        fut.set_result(user_password)

                    self.push_screen(PasswordModal(), modal_callback)
                    custom_password = await fut

                    if custom_password is not None:
                        log.write(f" 🔄 Retrying {mgr.name} upgrade with custom password...")
                        retry_cmd = ["sudo"] + cmd[1:] if is_pkexec else cmd
                        return await self._upgrade_manager(
                            mgr, password=custom_password, cmd_override=retry_cmd
                        )
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
        failures = []
        for i, mgr in enumerate(selected_instances, 1):
            if not await self._upgrade_manager(mgr):
                failures.append(mgr.name)
            progress.progress = int((i / total_steps) * 100)

        if failures:
            failed = ", ".join(failures)
            log.write(f"[bold yellow]⚠️ Upgrade finished with failures: {escape(failed)}.[/bold yellow]")
            await self._send_phone_notification(f"⚠️ Package upgrades failed: {failed}")
        else:
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
        failures = []
        for i, mgr in enumerate(self.managers, 1):
            if not await self._upgrade_manager(mgr):
                failures.append(mgr.name)
            progress.progress = int((i / total_steps) * 100)

        if failures:
            failed = ", ".join(failures)
            log.write(f"[bold yellow]⚠️ Full upgrade finished with failures: {escape(failed)}.[/bold yellow]")
            await self._send_phone_notification(f"⚠️ Full upgrades failed: {failed}")
        else:
            log.write("[bold green]🎉 Full system upgrade completed successfully.[/bold green]")
            await self._send_phone_notification("🎉 Full system upgrades completed.")
