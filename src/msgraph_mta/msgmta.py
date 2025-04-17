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
import sys

from datetime import datetime
from pathlib import Path

import requests

from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]
VERBOSE = False


def vprint(*args, **kwargs):
    """
    print if verbose
    """
    if not VERBOSE:
        return
    print(*args, **kwargs)


def load_config(configfile):
    """
    loads confing fron a json file
    Multiple sender profiles could be in the json file
    but currently only the "default" profile is taken
    """
    cfg_path = Path(configfile)
    # TODO: could refuse (similar to ssh) reading the
    # TODO: file if group or otherts can read the file
    with cfg_path.open() as fin:
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
        client_credential=config["client_secret"]
    )

    result = app.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Could not obtain token: {result}")
    return result["access_token"]


def fmt_recipients(recipients):
    """
    convert a list of recipient emails into a list
    of dict required for MSGraph
    """
    return [
        {"emailAddress": {"address": addr.strip()}}
        for addr in recipients
    ]


def parse_email_message(raw_data):
    """
    parse incoming message and extract headers
    """
    msg = email.message_from_string(raw_data)

    to_addrs = msg.get_all("To", [])
    cc_addrs = msg.get_all("Cc", [])
    bcc_addrs = msg.get_all("Bcc", [])
    assert not bcc_addrs, "must implement bcc handling"

    # ChatGpt said that: Microsoft Graph does not support BCC directly
    # — skip it or handle differently
    # TODO: Check if true and handle in forloop

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
            "from": {
                "emailAddress": {"address": sender}
            }
        },
        "saveToSentItems": "true"
    }

    response = requests.post(
        f"{GRAPH_ENDPOINT}/users/{sender}/sendMail",
        headers=headers,
        json=data
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
    parser.add_argument('--from', '-f')
    parser.add_argument('recipients', nargs='*')
    return parser


def main():
    global VERBOSE
    options = mk_parser().parse_args()
    VERBOSE = options.verbose
    debug = options.debug
    print(f"{options.debug_path}")
    if debug_path := options.debug_path:
        debug_path = Path(options.debug_path)

    raw_email = sys.stdin.read()
    if debug:
        debug_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        raw_path = debug_path / f"{now}.raw"
        ctr = 0
        while raw_path.exists():
            ctr += 1
            raw_path = Path(f"{now}_{ctr}.raw")
        with raw_path.open("w") as fout:
            fout.write(raw_email)

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
    parsed['subject'] = parsed['subject'] or options.subject
    vprint(f"{parsed['to']=}")
    vprint(f"{parsed['cc']=}")
    vprint(f"{parsed['bcc']=}")
    vprint(f"{parsed['subject']=}")
    if debug:
        with raw_path.with_suffix(".tkn").open("w") as fout:
            fout.write(token)
        with raw_path.with_suffix(".json").open("w") as fout:
            json.dump(parsed, fout, indent=1)

    if not parsed['to']:
        logger.error("No recipients found in email headers")
        sys.exit(1)

    send_mail(token, sender, parsed)


if __name__ == '__main__':
    main()
