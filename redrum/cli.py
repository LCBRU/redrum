import re
import subprocess
import tempfile
import tomllib
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from looseversion import LooseVersion
from platformdirs import PlatformDirs
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

platform_dirs = PlatformDirs("redrum", "lbrc")
console = Console()

DEFAULT_CONFIG: dict[str, Any] = {
    "download_path": platform_dirs.user_downloads_dir,
    "servers": {},
    "ssh_hostname_regex": None,
    "redcap_directory": "/local/www/htdocs",
}


def load_config() -> dict:
    path = Path(platform_dirs.user_config_dir) / "config.toml"

    if not path.is_file():
        return DEFAULT_CONFIG.copy()

    with path.open("rb") as file:
        return DEFAULT_CONFIG | tomllib.load(file)


config = load_config()


def select_item_from_list(title: str, items: list[str]) -> str|None:

    if not items:
        return None

    table = Table(title=title)

    table.add_column("Option", justify="right", style="cyan", no_wrap=True)
    table.add_column("File", style="magenta")

    for i, f in enumerate(items, 1):
        table.add_row(str(i), f)

    console.clear()
    console.print(table)

    result = Prompt.ask(
        "Select an option or 'q' to quit",
        choices=[str(i) for i in range(1, len(items) + 1)] + ["q"],
        default="q",
    )

    if result.isnumeric():
        return items[int(result) - 1]


def select_upgrade_file() -> Path | None:
    download_directory = Path(config["download_path"])

    upgrade_files = sorted(
        [
            f.stem.removeprefix("redcap")
            for f in download_directory.glob("redcap*.zip")
        ],
        key=LooseVersion,
    )

    result = select_item_from_list(
        title="Available Upgrade Files",
        items=upgrade_files,
    )

    if result:
        return download_directory / f'redcap{result}.zip'


def get_hostnames_from_ssh_config() ->list[str]:
    ssh_config = Path.home() / ".ssh" / "config"
    if not ssh_config.is_file():
        return []

    hostnames = []
    with ssh_config.open() as file:
        for line in file:
            fields = line.split("#", 1)[0].split()
            if len(fields) < 2 or fields[0].lower() != "host":
                continue

            hostnames.extend(
                hostname
                for hostname in fields[1:]
                if not any(char in hostname for char in "*!?")
            )

    if config["ssh_hostname_regex"]:
        hostnames = sorted([
            hostname
            for hostname in hostnames
            if re.search(config["ssh_hostname_regex"], hostname)
        ])

    return [{
        "hostname": h,
    } for h in hostnames]


def select_server() -> dict | None:
    servers = config["servers"]

    if not servers:
        servers = get_hostnames_from_ssh_config()

    server_dict = {
        s['hostname']: s
        for s in servers
    }

    selected = select_item_from_list(
        title="Available Servers",
        items=server_dict.keys(),
    )

    if selected:
        return server_dict[selected]
    

@contextmanager
def redcap_folder(upgrade_file: Path) -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmpdirname:
        with zipfile.ZipFile(upgrade_file, 'r') as zip_ref:
            console.print(f'Unzipping file {upgrade_file} ...')
            zip_ref.extractall(tmpdirname)

        redcap_folder = next(Path(tmpdirname).glob('redcap/redcap_v[0-9]*'))

        yield redcap_folder


def upgrade_redcap(redcap_folder: Path, server: dict) -> None:
    console.print(
        f"Upgrading REDCap on server {server} using files from {redcap_folder} ..."
    )

    redcap_directory = server.get("redcap_directory", config["redcap_directory"])

    subprocess.check_output(['scp', '-r', redcap_folder, f'{server}:{redcap_directory}'])

    console.print(f"[green]Upgrade completed successfully on server {server}.[/green]")
    Prompt.ask(
        "[orange]Package copied.  Complete the upgrade in the REDCap front "
        "end...[/orange]"
    )


def main() -> None:
    print("Running REDRUM...")

    upgrade_file = select_upgrade_file()

    if upgrade_file:
        with redcap_folder(upgrade_file) as rf:
            while server := select_server():
                upgrade_redcap(rf, server)


if __name__ == "__main__":
    main()
