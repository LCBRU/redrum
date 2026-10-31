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
    "servers": [],
    "ssh_config_path": Path.home() / ".ssh" / "config",
    "ssh_hostname_regex": None,
    "redcap_directory": "/var/www/htdocs",
}


def load_config() -> dict:
    path = Path(platform_dirs.user_config_dir) / "config.toml"

    if not path.is_file():
        return DEFAULT_CONFIG.copy()

    with path.open("rb") as file:
        return DEFAULT_CONFIG | tomllib.load(file)


config = load_config()


def select_item_from_list(title: str, columns: list[str], items: dict[str, dict[str, str]]) -> str|None:

    if not items:
        return None

    table = Table(title=title)

    table.add_column("Option", justify="right", style="cyan", no_wrap=True)

    for c in columns:
        table.add_column(c.title(), style="magenta")

    for i, (_, f) in enumerate(items.items(), 1):
        print(f)
        cols = [str(i)]

        for c in columns:
            cols.append(f[c])

        table.add_row(*cols)

    console.clear()
    console.print(table)

    result = Prompt.ask(
        "Select an option or 'q' to quit",
        choices=[str(i) for i in range(1, len(items) + 1)] + ["q"],
        default="q",
    )

    if result.isnumeric():
        return list(items.keys())[int(result) - 1]


def select_upgrade_file() -> Path | None:
    download_directory = Path(config["download_path"])

    upgrade_files = sorted(
        [
            f.stem.removeprefix("redcap")
            for f in download_directory.glob("redcap*.zip")
        ],
        key=LooseVersion,
    )

    uf_dict = {
        f: {"file": f}
        for f in upgrade_files
    }

    result = select_item_from_list(
        title="Available Upgrade Files",
        columns=['file'],
        items=uf_dict,
    )

    if result:
        return download_directory / f'redcap{result}.zip'


def get_hostnames_from_ssh_config() ->list[str]:
    ssh_config = Path(config["ssh_config_path"])

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
    DEFAULT_SERVER: dict[str, Any] = {
        "redcap_directory": config["redcap_directory"],
    }

    servers = config["servers"]

    if not servers:
        servers = get_hostnames_from_ssh_config()

    server_dict = {
        s['hostname']: DEFAULT_SERVER | s
        for s in servers
    }

    selected = select_item_from_list(
        title="Available Servers",
        columns=['hostname', 'redcap_directory'],
        items=server_dict,
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

    subprocess.check_output(['scp', '-r', redcap_folder, f'{server["hostname"]}:{server["redcap_directory"]}'])

    console.print(
        f"[green]Upgrade completed successfully on server {server['hostname']} "
        f"to directory {server['redcap_directory']}.[/green]"
    )
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
