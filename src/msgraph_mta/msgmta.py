#!/usr/bin/env python

# #############################################################################
# Copyright : (C) 2024 by MHComm. All rights reserved
#
# Name       :  msgraph_mta.msgmta
"""
  Summary : send mail via graph

__author__ = "Klaus Foerster"
__email__ = "info@mhcomm.fr"

Simple MTA that sends mails via msgraph
"""
# #############################################################################
import argparse
import email
import json
import logging
import os
import stat
import sys

from datetime import datetime
from email.utils import getaddresses
from pathlib import Path

import requests

from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]
# max time in seconds to wait for an answer of a server
REQUEST_TIMEOUT = 30
VERBOSE = False


def vprint(*args, **kwargs):
    """
    print if verbose
    """
    if not VERBOSE:
        return
    print(*args, **kwargs)


def create_private(path):
    """
    create a new file, that only the owner can read or write
    and return it opened for writing.

    raises FileExistsError if the file exists already (symlinks included)
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    return os.fdopen(os.open(path, flags, 0o600), "w")


def save_raw_email(debug_path, raw_email):
    """
    save the raw mail in a new file below debug_path
    and return the path of this file.

    The file name is derived from the current time. A counter is appended
    if a file with this name exists already.
    """
    debug_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    raw_path = debug_path / f"{now}.raw"
    ctr = 0
    while True:
        try:
            # creating and checking for existence in one step avoids, that
            # two processes started at the same time use the same file
            fout = create_private(raw_path)
        except FileExistsError:
            ctr += 1
            raw_path = debug_path / f"{now}_{ctr}.raw"
            continue
        with fout:
            fout.write(raw_email)
        return raw_path


def load_config(configfile):
    """
    loads config from a json file
    Multiple sender profiles could be in the json file
    but currently only the "default" profile is taken
    """
    cfg_path = Path(configfile)
    with cfg_path.open() as fin:
        # The file contains a secret. Refuse it (similar to ssh) if
        # everybody can read or modify it.
        # Access for the group is tolerated (see MSGMTA_GROUP in msgmta.sh)
        mode = os.fstat(fin.fileno()).st_mode
        if mode & (stat.S_IROTH | stat.S_IWOTH):
            raise PermissionError(
                f"permissions {stat.S_IMODE(mode):04o} of {cfg_path} are too"
                " open: the file must not be accessible by others"
                f" (fix with: chmod o-rwx {cfg_path})"
            )
        data = json.load(fin)
        entry = data["default"]
        return {
            "tenant_id": entry["tenant_id"],
            "client_id": entry["application_id"],
            "client_secret": entry["secret_value"],
            "from_address": entry["sender"],
        }


def get_access_token(config):
    """
    request and return an access token.
    """
    app = ConfidentialClientApplication(
        config["client_id"],
        authority=f"https://login.microsoftonline.com/{config['tenant_id']}",
        client_credential=config["client_secret"],
        timeout=REQUEST_TIMEOUT,
    )

    result = app.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Could not obtain token: {result}")
    return result["access_token"]


def fmt_recipients(recipients):
    """
    convert a list of recipient emails into a list
    of dicts required for MSGraph

    Each entry may be a bare address, a "Name <addr>" form or a
    comma separated list of these (as found in mail headers).
    """
    return [
        {"emailAddress": {"address": addr.strip()}}
        for _name, addr in getaddresses(recipients)
        if addr.strip()
    ]


def deduplicate(recipients):
    """
    remove duplicate addresses from a list of recipients
    (as returned by fmt_recipients)

    The comparison is case insensitive, the first occurrence is kept.
    """
    seen = set()
    result = []
    for recipient in recipients:
        key = recipient["emailAddress"]["address"].lower()
        if key not in seen:
            seen.add(key)
            result.append(recipient)
    return result


def parse_email_message(raw_data):
    """
    parse incoming message and extract headers
    """
    msg = email.message_from_string(raw_data)

    to_addrs = msg.get_all("To", [])
    cc_addrs = msg.get_all("Cc", [])
    bcc_addrs = msg.get_all("Bcc", [])

    parsed = {
        "to": fmt_recipients(to_addrs),
        "cc": fmt_recipients(cc_addrs),
        "bcc": fmt_recipients(bcc_addrs),
        "subject":  msg.get("Subject", ""),
        "content_type": "text/plain",
    }

    content = ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                content = (
                    part.get_payload(decode=True)
                    .decode(part.get_content_charset("utf-8"))
                )
                break
    else:
        content = (
            msg.get_payload(decode=True)
            .decode(msg.get_content_charset("utf-8"))
        )

    parsed["content"] = content

    return parsed


def send_mail(token, sender, parsed):
    """
    send mail via MSGraph
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "message": {
            "subject": parsed['subject'],
            "body": {
                "contentType": "Text",
                "content": parsed['content']
            },
            "toRecipients": parsed['to'],
            "ccRecipients": parsed['cc'],
            "bccRecipients": parsed['bcc'],
            "from": {
                "emailAddress": {"address": sender}
            }
        },
        "saveToSentItems": "true"
    }

    response = requests.post(
        f"{GRAPH_ENDPOINT}/users/{sender}/sendMail",
        headers=headers,
        json=data,
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        raise Exception(
            f"Graph sendMail failed: {response.status_code} {response.text}")

    logger.info("Message sent successfully")


def mk_parser():
    """
    commandline parser
    """
    description = "no description given"
    default_cfg = str(Path.home() / ".config" / "msgmta.json")
    default_cfg = os.environ.get("MSGMTA_CONFIG", default_cfg)
    default_debug_enabled = (
        os.environ.get("MSGMTA_DEBUG", "false")[:1].lower()
        in ("1", "t", "y")
    )
    default_debug_path = os.environ.get("MSGMTA_DEBUG_PATH", ".")

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        '--config',
        '-c',
        default=default_cfg,
        help="config file to read from: default=%(default)s",
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action="store_true",
        help="be a little more verbose",
    )
    parser.add_argument(
        '--debug',
        '-d',
        action="store_true",
        default=default_debug_enabled,
        help=(
            "store debug data (can also be"
            + " activated with MSGMTA_DEBUG=true)"
        ),
    )
    parser.add_argument(
        '--debug-path',
        '-D',
        default=default_debug_path,
        help="path where to store debug data",
    )
    parser.add_argument('--subject', '-s', default="no subject")
    parser.add_argument('--from-email', '-f')
    parser.add_argument('recipients', nargs='*')
    return parser


def main():
    global VERBOSE
    options = mk_parser().parse_args()
    VERBOSE = options.verbose
    debug = options.debug
    if debug_path := options.debug_path:
        debug_path = Path(options.debug_path)
    vprint(f"{debug_path=}")

    raw_email = sys.stdin.read()
    if debug:
        raw_path = save_raw_email(debug_path, raw_email)

    cfg_path = Path(options.config)
    config = load_config(cfg_path)
    sender = config["from_address"]
    token = get_access_token(config)

    parsed = parse_email_message(raw_email)

    vprint(
        f"parsed: {parsed['subject']}, "
        + f"{parsed['to']}, {parsed['cc']}, {parsed['bcc']}, "
        + f"{parsed['content_type']}, {parsed['content']}"
    )

    parsed['to'] = parsed['to'] or []
    parsed['to'].extend(fmt_recipients(options.recipients))
    for field in ("to", "cc", "bcc"):
        parsed[field] = deduplicate(parsed[field])
    parsed['subject'] = parsed['subject'] or options.subject
    vprint(f"{parsed['to']=}")
    vprint(f"{parsed['cc']=}")
    vprint(f"{parsed['bcc']=}")
    vprint(f"{parsed['subject']=}")
    if debug:
        with create_private(raw_path.with_suffix(".json")) as fout:
            json.dump(parsed, fout, indent=1)

    if not parsed['to']:
        logger.error("No recipients found in email headers")
        sys.exit(1)

    send_mail(token, sender, parsed)


if __name__ == '__main__':
    main()
