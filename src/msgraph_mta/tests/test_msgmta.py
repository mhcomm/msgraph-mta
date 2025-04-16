import sys

from pathlib import Path
from unittest.mock import patch

import pytest

import msgraph_mta.msgmta

def mk_args(*args):
    newargs = [
        str(Path(msgraph_mta.msgmta.__file__).resolve())
    ] + list(args)
    return newargs

def test_show_help(capsys):
    newargs = mk_args("-h")
    print(f"{newargs}")
    with patch.object(sys, "argv", newargs):
        with pytest.raises(SystemExit):
            msgraph_mta.msgmta.main()
        captured = capsys.readouterr().out
        with capsys.disabled():
            print(captured)
        assert "usage: msgmta" in captured


