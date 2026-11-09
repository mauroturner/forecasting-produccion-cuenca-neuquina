"""The Airflow compose file and its image: nothing exposed beyond the machine, no default secrets, a read-only code mount, same pins as the CLI (A1, A2)."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
AIRFLOW = PROJECT / "airflow"
COMPOSE = (AIRFLOW / "docker-compose.yaml").read_text(encoding="utf-8")
DOCKERFILE = (AIRFLOW / "Dockerfile").read_text(encoding="utf-8")
ENV_EXAMPLE = (AIRFLOW / ".env.example").read_text(encoding="utf-8")
SECRETS = ("FERNET_KEY", "AIRFLOW__API_AUTH__JWT_SECRET", "_AIRFLOW_WWW_USER_PASSWORD")


def code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_the_interface_is_published_on_the_loopback_address_only() -> None:
    published = re.findall(r'^\s*-\s*"?(\d[\d.]*:\d+:\d+|\d+:\d+)"?\s*$', "\n".join(code_lines(COMPOSE)), flags=re.MULTILINE)
    assert published and all(entry.startswith("127.0.0.1:") for entry in published)


def test_the_secrets_come_from_the_environment_and_have_no_default() -> None:
    lines = code_lines(COMPOSE)
    for name in SECRETS:
        uses = [line for line in lines if "${" + name in line]
        assert uses, name
        assert all("${" + name + ":?" in line for line in uses), f"{name} needs a required variable (${{{name}:?...}}), not a default"
        assert re.search(rf"^{name}=\s*$", ENV_EXAMPLE, flags=re.MULTILINE), f"{name} must be listed, empty, in .env.example"


def test_the_code_and_the_configuration_are_mounted_read_only_and_only_the_outputs_are_writable() -> None:
    mounts = [line.split("-", 1)[1].strip() for line in code_lines(COMPOSE) if re.match(r"\s*-\s*\.\./", line)]
    assert "..:/opt/oilgas" not in mounts  # the whole project, writable, is no longer mounted
    read_only = {m.split(":")[0] for m in mounts if m.endswith(":ro")}
    writable = {m.split(":")[0] for m in mounts if not m.endswith(":ro")}
    assert {"../src", "../config", "../sql"} <= read_only
    assert writable == {"../data", "../outputs", "../reports", "../dashboard"}


def test_the_images_are_pinned_by_an_explicit_version_tag() -> None:
    images = re.findall(r"^\s*image:\s*(\S+)\s*$", COMPOSE, flags=re.MULTILINE) + re.findall(r"^FROM\s+(\S+)", DOCKERFILE, flags=re.MULTILINE)
    assert images
    for image in images:
        _, _, tag = image.partition(":")
        assert re.fullmatch(r"\d+(\.\d+)+", tag), f"{image} has no explicit version tag"


def test_the_airflow_image_installs_the_exact_pins_of_the_command_line() -> None:
    assert "COPY requirements.txt" in DOCKERFILE and "-r /requirements.txt" in DOCKERFILE
    assert not (AIRFLOW / "requirements-airflow.txt").exists()  # no second list with ranges
    pins = code_lines((PROJECT / "requirements.txt").read_text(encoding="utf-8"))
    assert pins and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][^\s]*", line) for line in pins)
    assert re.search(r"context:\s*\.\.\s*\n\s*dockerfile:\s*airflow/Dockerfile", COMPOSE)  # the build sees requirements.txt
