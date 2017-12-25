import getpass
import hashlib
import re
import sys

from twisted.python import log

GRAVATAR_URL = 'http://www.gravatar.com/avatar/{}?s=48&r=any&default=identicon'

if getpass.getuser() == 'nobody':
    IRC_HOST = 'irc.ocf.berkeley.edu'
else:
    IRC_HOST = 'dev-irc.ocf.berkeley.edu'

IRC_PORT = 6697

# TODO: Actually have a more complete mapping of emoji names to symbols
EMOJIS = {
    '+1': '+1',
    '-1': '-1',
    'angry': '>:(',
    'anguished': 'D:',
    'astonished': ':O',
    'broken_heart': '</3',
    'confused': ':/',
    'cry': ':\'(',
    'disappointed': ':(',
    'frowning': ':(',
    'grin': ':D',
    'heart': '<3',
    'kiss': ':*',
    'laughing': 'xD',
    'monkey_face': ':o)',
    'neutral_face': ':|',
    'no_mounth': ':-',
    'open_mouth': ':o',
    'simple_smile': ':)',
    'slightly_smiling_face': ':)',
    'smile': ':D',
    'smiley': ':-)',
    'smirk': ';)',
    'stuck_out_tongue': ':P',
    'stuck_out_tongue_winking_eye': ';P',
    'sunglasses': '8)',
    'sweat': '\':(',
    'sweat_smile': '\':)',
    'tired_face': 'x.x',
    'thumbsdown': '-1',
    'thumbsup': '+1',
    'weary': 'x.x',
    'wink': ';)',
}


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


def format_irc_message(text, users, channels):
    def chan_replace(match):
        chan_id = match.group(1)
        readable = match.group(2)
        return '#{}'.format(readable or channels[chan_id])

    def user_replace(match):
        user_id = match.group(1)
        readable = match.group(2)
        return readable or users[user_id].nickname

    def cmd_replace(match):
        command = match.group(1)
        label = match.group(2)
        return '<{}>'.format(label or command)

    def emoji_replace(match):
        emoji = match.group(1)
        if emoji in EMOJIS:
            return EMOJIS[emoji]
        return ':{}:'.format(emoji)

    text = re.sub(r'\n|\r', ' ', text)
    text = text.replace('<!channel>', '@channel') \
               .replace('<!everyone>', '@everyone') \
               .replace('<!here>', '@here')

    # Replace channels, users, commands, links, emoji, and any remaining stuff
    # Adapted from
    # https://github.com/ekmartin/slack-irc/blob/2b5ceb7ca7beb/lib/bot.js#L154
    text = re.sub(r'<#(C\w+)\|?(\w+)?>', chan_replace, text)
    text = re.sub(r'<\@(U\w+)\|?(\w+)?>', user_replace, text)
    text = re.sub(r'<!(\w+)\|?(\w+)?>', cmd_replace, text)
    text = re.sub(r'<(?!!)([^|]+?)>', lambda match: match.group(1), text)
    text = re.sub(r':([\d\w+-]+):', emoji_replace, text)
    text = re.sub(r'<.+?\|(.+?)>', lambda match: match.group(1), text)

    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text


def format_slack_message(text):
    # Strip any color codes coming from IRC, since Slack cannot display them
    # Current solution is taken from https://stackoverflow.com/a/970723
    # TODO: Preserve bold and italics (convert to markdown?)
    return re.sub(r'\x03(?:\d{1,2}(?:,\d{1,2})?)?', '', text, flags=re.UNICODE)


def slack_api(slack_client, *args, **kwargs):
    results = slack_client.api_call(*args, **kwargs)
    if results['ok']:
        return results
    else:
        log.err('Error calling Slack API: {}'.format(results))
        # TODO: Handle this better than exiting
        sys.exit(1)
