import getpass
import hashlib
import sys

from twisted.python import log

GRAVATAR_URL = 'http://www.gravatar.com/avatar/{}?s=48&r=any&default=identicon'

if getpass.getuser() == 'nobody':
    IRC_HOST = 'irc.ocf.berkeley.edu'
else:
    IRC_HOST = 'dev-irc.ocf.berkeley.edu'

IRC_PORT = 6697


def user_to_gravatar(user):
    email_hash = hashlib.md5()
    email = '{}@ocf.berkeley.edu'.format(user)
    email_hash.update(email.encode())
    return GRAVATAR_URL.format(email_hash.hexdigest())


def strip_nick(nick):
    # This seems nicer than an ugly regex with a ton of escaping
    allowed_chars = '_-\\[]{}^`|'

    # Remove any characters that are not alphanumberic, an underscore, or not
    # in the list of allowed characters

    return ''.join([
        c
        if c.isalnum() or c in allowed_chars
        else ''
        for c in nick
    ])


def slack_api(slack_client, *args, **kwargs):
    results = slack_client.api_call(*args, **kwargs)
    if results['ok']:
        return results
    else:
        log.err('Error calling Slack API: {}'.format(results))
        # TODO: Handle this better than exiting
        sys.exit(1)
