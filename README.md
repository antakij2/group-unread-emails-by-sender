# Group Unread Emails by Sender

Moves all unread emails from your Inbox into new folders on your IMAP mail server based on sender.

## Dependencies

- Python 3.6 or newer

## How to run

You could run 

    python group_unread_emails_by_sender.py <arguments...>

but your shell's history log may contain your email password if you type it out as an argument on the command line.
To avoid this, you can instead list your arguments in a text file, e.g. `args.txt`, and run

    python group_unread_emails_by_sender.py --from-file args.txt
