#! /usr/bin/env python3

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# group_unread_emails_by_sender.py: Moves all unread emails from your Inbox into new folders based on sender. #
# Copyright (C) 2022  Joe Antaki  ->  joeantaki3 at gmail dot com                                             #
#                                                                                                             #
# This program is free software: you can redistribute it and/or modify                                        #
# it under the terms of the GNU General Public License as published by                                        #
# the Free Software Foundation, either version 3 of the License, or                                           #
# (at your option) any later version.                                                                         #
#                                                                                                             #
# This program is distributed in the hope that it will be useful,                                             #
# but WITHOUT ANY WARRANTY; without even the implied warranty of                                              #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the                                               #
# GNU General Public License for more details.                                                                #
#                                                                                                             #
# You should have received a copy of the GNU General Public License                                           #
# along with this program.  If not, see <https://www.gnu.org/licenses/>.                                      #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
import imaplib
import ssl
import time
import re
from collections import defaultdict

EMAIL_PATTERN = re.compile(r'<.+?>')
PROHIBITED_CHARACTERS_PATTERN = re.compile(r'[\W_]')
TRANSLATIONS = {'-':'DASH', '.':'DOT', '@':'AT'}
TRANSLATABLE_CHARACTERS_PATTERN = re.compile(fr'[{"".join(key for key in TRANSLATIONS)}]')
MAILBOX_PREFIX = 'Unread/'

# given a match object from a call to re.Pattern.sub, look up the match string in TRANSLATIONS and return
# the translation, if applicable (e.g. if the replacement character is "_", then "." translates to "_DOT_")
def translate_match(m):
    group = m.group()
    translation = TRANSLATIONS.get(group)
    if translation:
        return f"{_replacement_character}{translation}{_replacement_character}"

    return group

# create a mapping between sender/return-path email addresses (taken from a list of data from an IMAP server)
# and the UIDs of the emails sent by those addresses
def extract_email_addresses(data, uid_iterator):
    address_to_uid = defaultdict(list)
    leftovers = []
    i = 0

    while i < len(data):
        uid = next(uid_iterator)
        item = data[i]
        if isinstance(item, tuple):
            # the message has the expected attribute (sender/return-path) containing the email address
            item = bytes.decode(item[1])
            match = EMAIL_PATTERN.search(item)
            if match:
                # the email address is between < and >
                address = match.group()[1:-1]
            else:
                # the email address is listed without < and >
                address = item.split()[-1]

            # replace non-alphanumeric characters in the sender's address with their translation, if applicable
            # (e.g. "." -> "_DOT_"), or just replace with the replacement character (e.g. "_") otherwise
            sanitized_address = TRANSLATABLE_CHARACTERS_PATTERN.sub(translate_match, address)
            sanitized_address = PROHIBITED_CHARACTERS_PATTERN.sub(_replacement_character, sanitized_address)

            address_to_uid[sanitized_address].append(uid)
            i += 2
        else:
            # the message does not have the expected attribute. store the uid for later processing
            leftovers.append(uid)
            i += 1

    return address_to_uid, leftovers

# main function
def group_unread_emails_by_sender(mail_server, tls_port, email_address, password, wait_time, replacement_character):
    global _replacement_character
    _replacement_character = replacement_character

    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(mail_server, tls_port, ssl_context=context) as client:
        client.login(email_address, password)
        client.select()

        # wait for a predetermined amount of time, and then issue the next IMAP command.
        # Print the server response, the issued command, and an abbreviated version of
        # the command arguments to stdout
        def pause_and_print(function_name, *args):
            time.sleep(wait_time)
            tag, data = client.__getattribute__(function_name)(*args)

            call_info = ' '.join([f'{tag} {function_name}:'] + [str(a)[:40] for a in args])
            if tag == 'NO':
                raise Exception(call_info)

            print(call_info)
            return data

        # get list of all unread emails
        search_data = pause_and_print('uid', 'search', 'unseen')
        unseen_message_uids = bytes.decode(search_data[0]).split()

        # fetch the 'from' address of all unread emails
        # the order of from_data matches the order of the uids returned from the search operation
        from_data = pause_and_print('uid', 'fetch', ','.join(unseen_message_uids), "(BODY.PEEK[HEADER.FIELDS (FROM)])")
        iter_unseen_message_uids = iter(unseen_message_uids)
        from_address_to_uid, return_path_uids = extract_email_addresses(from_data, iter_unseen_message_uids)

        # if any emails didn't have a 'from' address, try to fetch their return-path instead
        return_path_data = pause_and_print('uid', 'fetch', ','.join(return_path_uids), "(BODY.PEEK[HEADER.FIELDS (RETURN-PATH)])")
        iter_return_path_uids = iter(return_path_uids)
        return_path_address_to_uid, leftovers = extract_email_addresses(return_path_data, iter_return_path_uids)

        # collect existing mailbox names
        mailbox_data = pause_and_print('list')
        extant_mailboxes = set()
        for line in mailbox_data:
            line = bytes.decode(line)
            quote_counter = 0
            for i, c in enumerate(line):
                if c == '"':
                    quote_counter += 1
                if quote_counter == 3:
                    break

            extant_mailboxes.add(line[i:][1:-1])

        # create mailboxes based on sender email addresses, and list all the unread emails from those senders in the
        # appropriate mailbox
        for address_to_uid in [from_address_to_uid, return_path_address_to_uid]:
            for address, uids in address_to_uid.items():
                mailbox_name = MAILBOX_PREFIX + address
                if mailbox_name not in extant_mailboxes:
                    pause_and_print('create', mailbox_name)
                    extant_mailboxes.add(mailbox_name)

                # we must copy messages to their new mailbox and then delete from inbox one at a time,
                # or else we could exceed available disk space
                for uid in uids:
                    pause_and_print('uid', 'copy', uid, mailbox_name)
                    pause_and_print('uid', 'store', uid, '+FLAGS.SILENT', r'(\Deleted)')
                    pause_and_print('expunge')

    print('Done.')
    if leftovers:
        print(f"Couldn't classify these {len(leftovers)} UIDs:", ', '.join(leftovers))

if __name__ == '__main__':
    import sys
    import shlex
    from argparse import ArgumentParser, RawDescriptionHelpFormatter
    from textwrap import TextWrapper

    WAIT_TIME_DEFAULT = 3.0
    REPLACEMENT_CHARACTER_DEFAULT = '_'
    FROM_FILE = '--from-file'
    WAIT_TIME = '--wait-time'

    wrapper = TextWrapper(width=80, break_long_words=False, replace_whitespace=False)
    def wrap_and_separate_with_newlines(*args):
        return '\n\n'.join(
            [
                '\n'.join(
                    wrapper.wrap(arg)
                )
                for arg in args
            ]
        )

    description = wrap_and_separate_with_newlines(
        'Moves all unread emails from your Inbox into new folders based on sender. '
        'Creates one new folder on your IMAP mail server for each unique sender of unread emails, '
        'moves all unread emails by that sender into that folder, and sets the folder\'s name '
        f'as the sender\'s address. All such folders are then grouped under one parent folder, named "{MAILBOX_PREFIX[:-1]}".'
    )
    epilog = wrap_and_separate_with_newlines(
        'Your shell\'s history log may contain your email password if you type it out as an argument on the command line. '
        f'To avoid this, you can read in the arguments to this script from a file instead, using the {FROM_FILE} option. '
        'The arguments in this file may be listed on one line, or you may split them across multiple lines. '
        'Arguments containing spaces should be surrounded by quotes, and a literal quote can be escaped by a backslash.',

        'Special cases of character replacement are the characters "@", ".", and "-": instead of the bare replacement '
        'character, they will be replaced with the strings "_AT_", "_DOT_", and "_DASH_", respectively. But the leading '
        'and trailing underscores in those strings are defaults: they will always match the supplied replacement '
        'character.',

        'Unread emails are moved to their respective folders one at a time, instead of in groups. '
        f'So if you have a lot of unread emails, then depending on {WAIT_TIME}, this script could take a long time.'
    )

    parser = ArgumentParser(formatter_class=RawDescriptionHelpFormatter, description=description, epilog=epilog)

    parser.add_argument('MAIL_SERVER', help='the hostname of the IMAP mail server to connect to')
    parser.add_argument('TLS_PORT', help='the port number that accepts TLS or SSL IMAP connections on the mail server',
                        type=int)
    parser.add_argument('EMAIL_ADDRESS', help='your full email address')
    parser.add_argument('PASSWORD', help='the password to your email account')
    parser.add_argument('-w', WAIT_TIME, help='how many seconds to wait between each command sent to the mail server '
                        f'(default: {WAIT_TIME_DEFAULT})', type=float, default=WAIT_TIME_DEFAULT)
    parser.add_argument('-r', '--replacement-character', help='the character that replaces non-letter and non-numeral '
                        f'characters when naming folders after email senders (default: "{REPLACEMENT_CHARACTER_DEFAULT}")',
                        default=REPLACEMENT_CHARACTER_DEFAULT)
    parser.add_argument('-f', FROM_FILE, help='read arguments from a file instead of from the command line. All other '
                        'arguments given on the command line are ignored if this option is specified')

    # manually check if the --from-file option was specified. If so, read arguments from the given file
    for i, argument in enumerate(sys.argv):
        if argument == FROM_FILE:
            if len(sys.argv) > i + 1:
                with open(sys.argv[i + 1]) as argsfile:
                    args = parser.parse_args(shlex.split(argsfile.read()))

                break
            else:
                parser.error(f'argument {FROM_FILE}: expected one argument')
    else:
        # the --from-file option was not specified, so take arguments from the command line
        args = parser.parse_args()

    group_unread_emails_by_sender(args.MAIL_SERVER, args.TLS_PORT, args.EMAIL_ADDRESS, args.PASSWORD, args.wait_time,
                                  args.replacement_character)
