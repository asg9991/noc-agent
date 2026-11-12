"""Backup + restore del estado del agente (P14).

El estado (audit.jsonl, watch.db, outbox+cooldown) contiene datos del
cliente en claro y no tenía backup. Sigue el esquema de backups de ops
(`~/projects/ops/scripts/engram-backup.sh`): snapshot WAL-safe, cifrado
age/openssl con passphrase desde env, staging local con rotación, y upload
al offsite vía google-agent CLI. En lab el offsite se simula con
--dry-run/--output; el camino de prod queda allanado sin pretender estar
probado. Verificación de P14: backup + restore probados de punta a punta.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup-estado.sh"


def _run(tmp_path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    full = {**os.environ, **(env or {})}
    full.setdefault("NOC_BACKUP_KEEP", "3")
    full.setdefault("NOC_BACKUP_DIR", str(tmp_path / "staging"))
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True,
        env=full, timeout=60)


def _mk_state(state: Path) -> dict[str, str]:
    """Estado de lab realista: audit + outbox JSONL, cooldown y watch.db."""
    state.mkdir(parents=True, exist_ok=True)
    (state / "audit.jsonl").write_text(
        '{"ts": "2026-11-09T00:00:00+00:00", "actor": "ana", '
        '"action": "route", "channel": "lab", "result": "L0", "detail": {}}\n',
        encoding="utf-8")
    (state / "outbox.jsonl").write_text(
        '{"ts": 1762000000.0, "kind": "alarma", "eventid": "e1"}\n',
        encoding="utf-8")
    (state / "outbox.jsonl.cooldown.json").write_text('{"e1": 1762000000.0}',
                                                     encoding="utf-8")
    conn = sqlite3.connect(state / "watch.db")
    conn.executescript(
        "CREATE TABLE observations (eventid TEXT PRIMARY KEY,"
        " host TEXT, status TEXT);"
        "INSERT INTO observations VALUES ('e1', 'server-sim-03', 'active');")
    conn.commit()
    conn.close()
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in state.iterdir() if p.name != "watch.db"}


def _db_rows(state: Path) -> list[tuple]:
    conn = sqlite3.connect(state / "watch.db")
    rows = conn.execute("SELECT * FROM observations").fetchall()
    conn.close()
    return rows


def test_backup_y_restore_de_punta_a_punta(tmp_path):
    state = tmp_path / "estado"
    hashes = _mk_state(state)
    staging = tmp_path / "staging"
    salida = tmp_path / "offsite-simulado"

    r = _run(tmp_path, "--state-dir", str(state), "--dry-run",
             "--output", str(salida), "--keep", "3")
    assert r.returncode == 0, r.stderr
    artefactos = list(salida.iterdir())
    assert len(artefactos) == 1 and artefactos[0].name.startswith(
        "noc-agent-estado-")
    assert artefactos[0].name.endswith(".tar.gz")  # sin passphrase: plano

    # desastre: se pierde el estado
    for p in list(state.iterdir()):
        p.unlink()
    r = _run(tmp_path, "--restore", str(artefactos[0]), "--state-dir", str(state))
    assert r.returncode == 0, r.stderr
    for nombre, esperado in hashes.items():
        assert hashlib.sha256(
            (state / nombre).read_bytes()).hexdigest() == esperado
    assert _db_rows(state) == [("e1", "server-sim-03", "active")]


def test_restore_se_niega_a_pisar_sin_force(tmp_path):
    state = tmp_path / "estado"
    _mk_state(state)
    out = tmp_path / "salida"
    _run(tmp_path, "--state-dir", str(state), "--dry-run", "--output", str(out))
    arch = list(out.iterdir())[0]
    (state / "audit.jsonl").write_text('{"ts": "posterior"}\n', encoding="utf-8")

    r = _run(tmp_path, "--restore", str(arch), "--state-dir", str(state))
    assert r.returncode != 0
    assert "force" in (r.stdout + r.stderr).lower()
    assert "posterior" in (state / "audit.jsonl").read_text(encoding="utf-8")

    r = _run(tmp_path, "--restore", str(arch), "--state-dir", str(state), "--force")
    assert r.returncode == 0, r.stderr
    assert "posterior" not in (state / "audit.jsonl").read_text(encoding="utf-8")


def test_rotacion_conserva_keep(tmp_path):
    state = tmp_path / "estado"
    _mk_state(state)
    staging = tmp_path / "staging"
    env = {"NOC_BACKUP_DIR": str(staging)}
    for _ in range(3):
        r = _run(tmp_path, "--state-dir", str(state), "--dry-run", "--keep", "2",
                 env=env)
        assert r.returncode == 0, r.stderr
    assert len(list(staging.iterdir())) == 2


def test_restore_verifica_checksums_del_manifest(tmp_path):
    state = tmp_path / "estado"
    _mk_state(state)
    out = tmp_path / "salida"
    _run(tmp_path, "--state-dir", str(state), "--dry-run", "--output", str(out))
    arch = list(out.iterdir())[0]
    # tamper: reemplazar el contenido del audit dentro del tar
    import tarfile
    import io
    data = tmp_path / "tamper.tar.gz"
    with tarfile.open(arch) as src, tarfile.open(data, "w:gz") as dst:
        for m in src.getmembers():
            payload = src.extractfile(m).read()
            if m.name.endswith("audit.jsonl"):
                payload = b'{"ts": "falsificado"}\n'
            m.size = len(payload)
            dst.addfile(m, io.BytesIO(payload))
    for p in list(state.iterdir()):
        p.unlink()
    r = _run(tmp_path, "--restore", str(data), "--state-dir", str(state))
    assert r.returncode != 0
    assert "sha256" in (r.stdout + r.stderr).lower()


@pytest.mark.skipif(shutil.which("age") is None
                    or shutil.which("script") is None,
                    reason="requiere age + script(1) para cifrado no interactivo")
def test_cifrado_con_passphrase_roundtrip(tmp_path):
    state = tmp_path / "estado"
    hashes = _mk_state(state)
    out = tmp_path / "salida"
    env = {"NOC_BACKUP_PASSPHRASE": "pass-de-test"}
    r = _run(tmp_path, "--state-dir", str(state), "--dry-run", "--output", str(out),
             env=env)
    assert r.returncode == 0, r.stderr
    arch = list(out.iterdir())[0]
    assert arch.name.endswith(".age")
    # el artefacto cifrado no contiene el estado en claro
    assert b"server-sim-03" not in arch.read_bytes()

    for p in list(state.iterdir()):
        p.unlink()
    r = _run(tmp_path, "--restore", str(arch), "--state-dir", str(state), env=env)
    assert r.returncode == 0, r.stderr
    for nombre, esperado in hashes.items():
        assert hashlib.sha256(
            (state / nombre).read_bytes()).hexdigest() == esperado


def test_uploader_exige_cifrado(tmp_path):
    """El camino de prod (offsite real) no acepta estado en claro."""
    state = tmp_path / "estado"
    _mk_state(state)
    r = _run(tmp_path, "--state-dir", str(state))  # sin --dry-run, sin passphrase
    assert r.returncode != 0
    assert "cifrad" in (r.stdout + r.stderr).lower()
