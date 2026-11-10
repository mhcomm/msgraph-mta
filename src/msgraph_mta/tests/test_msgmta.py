import json
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


def mk_config(tmp_path, mode):
    """
    create a config file with the given permissions
    """
    cfg_path = tmp_path / "msgmta.json"
    cfg_path.write_text(json.dumps({
        "default": {
            "tenant_id": "tenant",
            "application_id": "app",
            "secret_value": "secret",
            "sender": "s@x.org",
        }
    }))
    cfg_path.chmod(mode)
    return cfg_path


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o400])
def test_load_config(tmp_path, mode):
    """
    a config file, that others cannot access is accepted
    """
    config = msgraph_mta.msgmta.load_config(mk_config(tmp_path, mode))
    assert config == {
        "tenant_id": "tenant",
        "client_id": "app",
        "client_secret": "secret",
        "from_address": "s@x.org",
    }


@pytest.mark.parametrize("mode", [0o644, 0o604, 0o602, 0o666])
def test_load_config_refuses_open_permissions(tmp_path, mode):
    """
    a config file, that others can read or write is refused
    """
    with pytest.raises(PermissionError):
        msgraph_mta.msgmta.load_config(mk_config(tmp_path, mode))


def test_bcc_recipients():
    """
    Bcc recipients are passed to MSGraph in their own field
    """
    mod = msgraph_mta.msgmta
    raw = "To: a@x.org\nCc: c@x.org\nBcc: b@x.org, B@x.org\n\nbody\n"
    parsed = run_main([], raw).call_args.args[2]
    assert addrs(parsed["bcc"]) == ["b@x.org"]

    with patch.object(mod.requests, "post") as post:
        mod.send_mail("tkn", "s@x.org", parsed)
    message = post.call_args.kwargs["json"]["message"]
    assert addrs(message["toRecipients"]) == ["a@x.org"]
    assert addrs(message["ccRecipients"]) == ["c@x.org"]
    assert addrs(message["bccRecipients"]) == ["b@x.org"]
    assert "b@x.org" not in message["body"]["content"]


def test_requests_have_a_timeout():
    """
    neither the token request nor the send request can hang forever
    """
    mod = msgraph_mta.msgmta
    parsed = {
        "subject": "hi", "content": "body", "to": [], "cc": [], "bcc": [],
    }
    with patch.object(mod.requests, "post") as post:
        mod.send_mail("tkn", "s@x.org", parsed)
    assert post.call_args.kwargs["timeout"] == mod.REQUEST_TIMEOUT

    config = {"client_id": "app", "tenant_id": "tenant", "client_secret": "s"}
    with patch.object(mod, "ConfidentialClientApplication") as app_cls:
        app_cls.return_value.acquire_token_for_client.return_value = {
            "access_token": "tkn",
        }
        assert mod.get_access_token(config) == "tkn"
    assert app_cls.call_args.kwargs["timeout"] == mod.REQUEST_TIMEOUT


def test_token_error_is_short():
    """
    a failing token request reports the error, but not the whole answer
    """
    mod = msgraph_mta.msgmta
    config = {"client_id": "app", "tenant_id": "tenant", "client_secret": "s"}
    result = {
        "error": "invalid_client",
        "error_description": "bad secret",
        "correlation_id": "c0ffee",
    }
    with patch.object(mod, "ConfidentialClientApplication") as app_cls:
        app_cls.return_value.acquire_token_for_client.return_value = result
        with pytest.raises(Exception) as excinfo:
            mod.get_access_token(config)
    assert "invalid_client: bad secret" in str(excinfo.value)
    assert "c0ffee" not in str(excinfo.value)


def test_send_error_is_short():
    """
    a failing send request reports code and message of the error only
    """
    mod = msgraph_mta.msgmta
    parsed = {
        "subject": "hi", "content": "body", "to": [], "cc": [], "bcc": [],
    }
    with patch.object(mod.requests, "post") as post:
        response = post.return_value
        response.ok = False
        response.status_code = 403
        response.json.return_value = {
            "error": {
                "code": "ErrorAccessDenied",
                "message": "Access is denied.",
                "innerError": {"request-id": "c0ffee"},
            }
        }
        with pytest.raises(Exception) as excinfo:
            mod.send_mail("tkn", "s@x.org", parsed)
        assert "403 ErrorAccessDenied: Access is denied." in str(excinfo.value)
        assert "c0ffee" not in str(excinfo.value)

        # answer is not the expected json
        response.json.side_effect = ValueError("no json")
        response.reason = "Forbidden"
        with pytest.raises(Exception) as excinfo:
            mod.send_mail("tkn", "s@x.org", parsed)
        assert "403 Forbidden" in str(excinfo.value)
