"""A manager that cannot report outdated packages is 'not supported', never 'Up to date'."""
import asyncio
from unittest.mock import patch

from app.core.manager import PackageManager
from app.ui.tui import PolyGetTuiApp


class NoQuery(PackageManager):
    name = "NoQuery"
    category = "Universal"

    def is_available(self):
        return True

    async def check_updates(self):
        raise NotImplementedError("cannot report outdated packages")

    def get_upgrade_command(self, packages=None):
        return ["noquery", "upgrade"]


class Current(NoQuery):
    name = "Current"

    async def check_updates(self):
        return []


def test_unsupported_check_is_labelled_as_such_and_a_real_clean_result_still_says_up_to_date():
    async def run():
        with patch("app.ui.tui.discover_managers", return_value=[]), patch("app.ui.tui.shutil.which", return_value=None):
            app = PolyGetTuiApp()
            async with app.run_test():
                unsupported, current = NoQuery(), Current()
                app.checking_managers.add(unsupported.name)
                app.checking_managers.add(current.name)
                await app._scan_manager(unsupported)
                await app._scan_manager(current)
                assert unsupported.name not in app.checking_managers
                assert current.name not in app.checking_managers
                assert "Update check not supported" in app._get_manager_label(unsupported)
                assert "Up to date" not in app._get_manager_label(unsupported)
                assert "Up to date" in app._get_manager_label(current)
                assert app.unsupported_checks == {"NoQuery": "cannot report outdated packages"}
                assert "NoQuery" not in app.scan_errors  # unsupported is not a failure

    asyncio.run(run())


def test_a_later_successful_scan_clears_the_unsupported_mark():
    async def run():
        with patch("app.ui.tui.discover_managers", return_value=[]), patch("app.ui.tui.shutil.which", return_value=None):
            app = PolyGetTuiApp()
            async with app.run_test():
                mgr = NoQuery()
                await app._scan_manager(mgr)
                assert "NoQuery" in app.unsupported_checks
                mgr.check_updates = Current().check_updates   # the manager gained support
                await app._scan_manager(mgr)
                assert "NoQuery" not in app.unsupported_checks

    asyncio.run(run())
