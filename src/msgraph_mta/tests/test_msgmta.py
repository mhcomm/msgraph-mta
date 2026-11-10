import sys

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import msgraph_mta.msgmta


def mk_args(*args):
    """
    make sys.argv arguments
    """
    newargs = [
        str(Path(msgraph_mta.msgmta.__file__).resolve())
    ] + list(args)
    return newargs


def test_show_help(capsys):
    """
    can help be displayed
    """
    newargs = mk_args("-h")
    print(f"{newargs}")
    with patch.object(sys, "argv", newargs):
        with pytest.raises(SystemExit):
            msgraph_mta.msgmta.main()
        captured = capsys.readouterr().out
        with capsys.disabled():
            print(captured)
        assert "usage: msgmta" in captured


def addrs(entries):
    return [entry["emailAddress"]["address"] for entry in entries]


def test_fmt_recipients():
    """
    headers with multiple addresses are split into single addresses
    """
    rcpts = ["a@x.org, Bob <b@x.org>", " c@x.org "]
    formatted = msgraph_mta.msgmta.fmt_recipients(rcpts)
    assert addrs(formatted) == ["a@x.org", "b@x.org", "c@x.org"]


def test_deduplicate():
    """
    duplicates are removed (case insensitive), first occurrence is kept
    """
    mod = msgraph_mta.msgmta
    rcpts = mod.fmt_recipients(["a@x.org", "b@x.org", "A@X.org", "b@x.org"])
    assert addrs(mod.deduplicate(rcpts)) == ["a@x.org", "b@x.org"]
    assert mod.deduplicate([]) == []


def test_main_dedups_recipients():
    """
    recipients of the message and of the command line are deduplicated
    """
    mod = msgraph_mta.msgmta
    raw = "To: a@x.org, a@x.org\nCc: c@x.org, C@x.org\nSubject: hi\n\nbody\n"
    newargs = mk_args("A@x.org", "d@x.org", "d@x.org")
    cfg = {"from_address": "s@x.org"}
    with patch.object(sys, "argv", newargs), \
            patch.object(sys.stdin, "read", return_value=raw), \
            patch.object(mod, "load_config", return_value=cfg), \
            patch.object(mod, "get_access_token", return_value="tkn"), \
            patch.object(mod, "send_mail") as send_mail:
        mod.main()
    parsed = send_mail.call_args.args[2]
    assert addrs(parsed["to"]) == ["a@x.org", "d@x.org"]
    assert addrs(parsed["cc"]) == ["c@x.org"]


def run_main(args, raw):
    """
    run main with the given args and the given mail on stdin
    without contacting any server.
    returns the mock replacing send_mail
    """
    mod = msgraph_mta.msgmta
    cfg = {"from_address": "s@x.org"}
    with patch.object(sys, "argv", mk_args(*args)), \
            patch.object(sys.stdin, "read", return_value=raw), \
            patch.object(mod, "load_config", return_value=cfg), \
            patch.object(mod, "get_access_token", return_value="s3cr3t"), \
            patch.object(mod, "send_mail") as send_mail:
        mod.main()
    return send_mail


def test_create_private(tmp_path):
    """
    files are created for the owner only and never overwritten
    """
    path = tmp_path / "private.txt"
    with msgraph_mta.msgmta.create_private(path) as fout:
        fout.write("data")
    assert path.read_text() == "data"
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        msgraph_mta.msgmta.create_private(path)


def test_debug_files(tmp_path):
    """
    debug files are private and do not contain the access token
    """
    raw = "To: a@x.org\nSubject: hi\n\nbody\n"
    run_main(["--debug", "--debug-path", str(tmp_path)], raw)
    files = sorted(tmp_path.iterdir())
    assert [path.suffix for path in files] == [".json", ".raw"]
    for path in files:
        assert path.stat().st_mode & 0o777 == 0o600
        assert "s3cr3t" not in path.read_text()


def test_save_raw_email_collision(tmp_path):
    """
    mails saved within the same second end up in different files,
    which are all located in the debug directory
    """
    mod = msgraph_mta.msgmta
    debug_path = tmp_path / "debug"
    with patch.object(mod, "datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
        paths = [
            mod.save_raw_email(debug_path, f"mail {idx}")
            for idx in range(3)
        ]
    assert [path.name for path in paths] == [
        "2026-01-02T03:04:05.raw",
        "2026-01-02T03:04:05_1.raw",
        "2026-01-02T03:04:05_2.raw",
    ]
    for idx, path in enumerate(paths):
        assert path.parent == debug_path
        assert path.read_text() == f"mail {idx}"
