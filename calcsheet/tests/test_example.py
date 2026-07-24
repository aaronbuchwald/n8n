"""The example entrypoint: writes the card, reports FAIL, opens nothing."""

from __future__ import annotations

from pathlib import Path

from calcsheet.examples import capacity


def _refuse_to_open(*_args, **_kwargs):
    raise AssertionError("--no-open must not open a browser")


def test_entrypoint_writes_the_card_and_prints_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    # --no-open must not touch the browser at all.
    monkeypatch.setattr(capacity.webbrowser, "open", _refuse_to_open)

    assert capacity.main(["--no-open"]) == 0

    written = Path(tmp_path, "out", "capacity-check.html")
    assert written.exists()
    assert written.read_text(encoding="utf-8") == capacity.render()

    out = capsys.readouterr().out
    assert "out/capacity-check.html" in out
    assert "status: FAIL" in out
    assert "57.1 < 50 = False" in out
