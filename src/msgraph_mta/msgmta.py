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

from pathlib import Path

import requests

from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)
# CONFIG_FILE = Path.home() / ".msgraph-sendmail.json"
CONFIG_FILE = Path("secrets.json")
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as fin:
        data = json.load(fin)
        entry = data["lna1"]
        return {
            "tenant_id": entry["tenant_id"],
            "client_id": entry["application_id"],
            "client_secret": entry["secret_value"],
            "from_address": entry["sender"],
        }


def get_access_token(config):
    app = ConfidentialClientApplication(
        config["client_id"],
        authority=f"https://login.microsoftonline.com/{config['tenant_id']}",
        client_credential=config["client_secret"]
    )

    result = app.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Could not obtain token: {result}")
    return result["access_token"]


def parse_email_message(raw_data):
    msg = email.message_from_string(raw_data)

    to_addrs = msg.get_all("To", [])
    cc_addrs = msg.get_all("Cc", [])
    bcc_addrs = msg.get_all("Bcc", [])

    # Microsoft Graph does not support BCC directly — skip it or handle differently

    recipients = [{"emailAddress": {"address": addr.strip()}}
                  for addr in to_addrs + cc_addrs]

    subject = msg.get("Subject", "")
    content_type = "text/plain"
    content = ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                content = part.get_payload(decode=True).decode(part.get_content_charset("utf-8"))
                break
    else:
        content = msg.get_payload(decode=True).decode(msg.get_content_charset("utf-8"))

    return subject, recipients, content_type, content


def send_mail(token, sender, subject, recipients, content_type, content):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": content
            },
            "toRecipients": recipients,
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
        raise Exception(f"Graph sendMail failed: {response.status_code} {response.text}")

    logger.info("Message sent successfully")


def mk_parser():
    """ commandline parser """
    description = "no description given"
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--subject', '-s', default="no subject")
    parser.add_argument('recipients', nargs='*')
    return parser


def main():
    options = mk_parser().parse_args()
    raw_email = sys.stdin.read()
    config = load_config()
    token = get_access_token(config)
    subject, recipients, content_type, content = parse_email_message(raw_email)
    print(f"parsed: {(subject, recipients, content_type, content)}")

    recipients = recipients or []
    recipients.extend(options.recipients)
    subject = subject or options.subject
    print(f"{recipients=}")
    print(f"{subject=}")

    if not recipients:
        logger.error("No recipients found in email headers")
        sys.exit(1)

    send_mail(
        token,
        sender=config["from_address"],
        subject=subject,
        recipients=recipients,
        content_type=content_type,
        content=content
    )



if __name__ == '__main__':
    main()
