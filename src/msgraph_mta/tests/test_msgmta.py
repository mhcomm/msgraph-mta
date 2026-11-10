import sys

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
