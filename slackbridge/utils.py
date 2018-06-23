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
    """
    We use Gravatar images for users when they are mirrored as a guess that
    they have the same IRC nick as their OCF username, and so the email
    <nick>@ocf.berkeley.edu will give a representative image. This is also the
    same thing we use for images on the staff hours page, so this will work for
    most (active) staff.
    """
    email_hash = hashlib.md5()
    email = '{}@ocf.berkeley.edu'.format(user)
    email_hash.update(email.encode())
    return GRAVATAR_URL.format(email_hash.hexdigest())


def strip_nick(nick):
    """
    Strip a given Slack nickname to be IRC bot compatible. For instance, Slack
    allows users to have periods (.) in their name, but IRC does not allow
    periods in nicks, so we have to remove them first.

    We do this by removing any characters that are not alphanumberic, an
    underscore, or not in the list of allowed characters for IRC nicks.
    """
    # This seems nicer than an ugly regex with a ton of escaping
    allowed_chars = '_-\\[]{}^`|'

    return ''.join([
        c
        if c.isalnum() or c in allowed_chars
        else ''
        for c in nick
    ])


def nick_from_irc_user(irc_user):
    """
    User is like 'jvperrin!Jason@fireball.ocf.berkeley.edu' (nick!ident@host),
    but we only want the nickname so we can use that as the display user when
    the message is bridged to Slack.
    """
    assert irc_user.count('!') == 1
    return irc_user.split('!')[0]


def format_irc_message(text, users, channels):
    """
    Replace channels, users, commands, links, emoji, and any remaining stuff in
    messages from Slack to things that IRC users would have an easier time
    reading ("<#C8K86UQTF>" is not as easy to read as "#channel" for instance)

    Adapted from
    https://github.com/ekmartin/slack-irc/blob/2b5ceb7ca7beb/lib/bot.js#L154
    """

    def chan_replace(match):
        """
        Replace channel references (e.g. "<#C6QASJWLA|rebuild>" with
        "#rebuild") to make them more readable
        """
        chan_id = match.group(1)
        readable = match.group(2)
        return '#{}'.format(readable or channels[chan_id])

    def user_replace(match):
        """
        Replace user references (e.g. "<@U0QHZCXST>" with "jvperrin-slack") to
        make them more readable. Uses the Slack user's IRC bot as the nick to
        reference to make thing more consistent (since another Slack user is
        being tagged, not an IRC user)
        """
        user_id = match.group(1)
        readable = match.group(2)
        return readable or users[user_id].nickname

    def var_replace(match):
        """
        Replace any variables sent from Slack with more readable counterparts
        (e.g. <!var|label> will display as <label> instead)
        """
        var = match.group(1)
        label = match.group(2)
        return '<{}>'.format(label or var)

    def emoji_replace(match):
        """
        Replace any emoji from Slack with more text-readable equivalents if
        they exist in the EMOJIS dict mapping (e.g. ":smile:" maps to ":D")
        If a mapping doesn't exist, it will just display the emoji as it was
        before, and hopefully the text explanation is enough. We can't hope to
        cover all emoji either, as they are a ton of them, not all have text
        representations, and you can even add custom ones to Slack!

        TODO: Map emoji to the unicode equivalent if they are not found in the
        simple mapping above.
        """
        emoji = match.group(1)
        if emoji in EMOJIS:
            return EMOJIS[emoji]
        return ':{}:'.format(emoji)

    # Remove newlines and carriage returns, since IRC doesn't have multi-line
    # messages, but Slack allows them
    text = re.sub(r'\n|\r', ' ', text)
    text = text.replace('<!channel>', '@channel') \
               .replace('<!everyone>', '@everyone') \
               .replace('<!here>', '@here')

    text = re.sub(r'<#(C\w+)\|?(\w+)?>', chan_replace, text)
    text = re.sub(r'<\@(U\w+)\|?(\w+)?>', user_replace, text)
    text = re.sub(r'<!(\w+)\|?(\w+)?>', var_replace, text)
    text = re.sub(r'<(?!!)([^|]+?)>', lambda match: match.group(1), text)
    text = re.sub(r':([\d\w+-]+):', emoji_replace, text)
    text = re.sub(r'<.+?\|(.+?)>', lambda match: match.group(1), text)

    # Slack gives <, >, and & as HTML-encoded entities, so we want to decode
    # them before posting them to IRC
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text


def format_slack_message(text, users):
    """
    Strip any color codes coming from IRC, since Slack cannot display them
    The current solution is taken from https://stackoverflow.com/a/970723
    We don't have to worry about encoding >, <, and & here to their
    HTML-escaped equivalents, because Slack's Python client already does this
    for us.

    TODO: Preserve bold and italics (convert to markdown?)
    """

    def nick_replace(match):
        """
        Replace any IRC nick of the form keur to <@keur> if it exists in
        the provided list of Slack display names. To prevent accidental
        conversions, "no-more-slack" will not be converted to "<@no-more>",
        assuming no user has the display name "no-more" in the Workspace.
        """
        nick = match.group(1)
        if nick in users:
            return '<@{}>'.format(nick)

    text = re.sub(r'\x03(?:\d{1,2}(?:,\d{1,2})?)?', '', text, flags=re.UNICODE)
    # we can be greedy here; nick is checked against valid list of users
    text = re.sub(r'([^\s]+)-slack', nick_replace, text)
    return text


def slack_api(slack_client, *args, **kwargs):
    results = slack_client.api_call(*args, **kwargs)
    if results['ok']:
        return results
    else:
        log.err('Error calling Slack API: {}'.format(results))
        # TODO: Handle this better than exiting
        sys.exit(1)
