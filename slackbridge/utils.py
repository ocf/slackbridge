from __future__ import annotations

import getpass
import hashlib
import re
import sys
from typing import Any
from typing import Match

from emoji import emojize
from slackclient import SlackClient
from twisted.python import log


GRAVATAR_URL = 'http://www.gravatar.com/avatar/{}?s=48&r=any&default=identicon'

if getpass.getuser() == 'nobody':
    IRC_HOST = 'irc.ocf.berkeley.edu'
else:
    IRC_HOST = 'dev-irc.ocf.berkeley.edu'

IRC_PORT = 6697


def user_to_gravatar(user: str) -> str:
    """
    We use Gravatar images for users when they are mirrored as a guess that
    they have the same IRC nick as their OCF username, and so the email
    <nick>@ocf.berkeley.edu will give a representative image. This is also the
    same thing we use for images on the staff hours page, so this will work for
    most (active) staff.
    """
    email_hash = hashlib.md5()
    email = f'{user}@ocf.berkeley.edu'
    email_hash.update(email.encode())
    return GRAVATAR_URL.format(email_hash.hexdigest())


def strip_nick(nick: str) -> str:
    """
    Strip a given Slack nickname to be IRC bot compatible. For instance, Slack
    allows users to have periods (.) in their name, but IRC does not allow
    periods in nicks, so we have to remove them first.

    We do this by removing any characters that are not alphanumberic, an
    underscore, or not in the list of allowed characters for IRC nicks.
    """
    # This seems nicer than an ugly regex with a ton of escaping
    allowed_chars = '_-\\[]{}^`|'

    return ''.join(
        c
        if c.isalnum() or c in allowed_chars
        else ''
        for c in nick
    )


def nick_from_irc_user(irc_user: str) -> str:
    """
    User is like 'jvperrin!Jason@fireball.ocf.berkeley.edu' (nick!ident@host),
    but we only want the nickname so we can use that as the display user when
    the message is bridged to Slack.
    """
    assert irc_user.count('!') == 1
    return irc_user.split('!')[0]


def format_irc_message(
    text: str,
    users: dict[str, Any],
    bots: dict[str, Any],
    channels: dict[str, Any],
) -> str:
    """
    Replace channels, users, commands, links, emoji, and any remaining stuff in
    messages from Slack to things that IRC users would have an easier time
    reading ("<#C8K86UQTF>" is not as easy to read as "#channel" for instance)

    Adapted from
    https://github.com/ekmartin/slack-irc/blob/2b5ceb7ca7beb/lib/bot.js#L154
    """

    def chan_replace(match: Match[str]) -> str:
        """
        Replace channel references (e.g. "<#C6QASJWLA|rebuild>" with
        "#rebuild") to make them more readable
        """
        chan_id = match.group(1)
        readable = match.group(2)
        return f'#{readable or channels[chan_id].get('name')}'

    def user_replace(match: Match[str]) -> str:
        """
        Replace user references (e.g. "<@U0QHZCXST>" with "jvperrin-slack") to
        make them more readable. Uses the Slack user's IRC bot as the nick to
        reference to make thing more consistent (since another Slack user is
        being tagged, not an IRC user)
        """
        user_id = match.group(1)
        readable = match.group(2)

        if readable or user_id in users:
            return readable or users[user_id].nickname
        elif user_id in bots:
            return bots[user_id].nickname
        else:
            # This should never occur
            return 'unknown'

    def var_replace(match: Match[str]) -> str:
        """
        Replace any variables sent from Slack with more readable counterparts
        (e.g. <!var|label> will display as <label> instead)
        """
        var = match.group(1)
        label = match.group(2)
        return f'<{label or var}>'

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
    text = emojize(text, use_aliases=True)
    text = re.sub(r'<.+?\|(.+?)>', lambda match: match.group(1), text)

    # Slack gives <, >, and & as HTML-encoded entities, so we want to decode
    # them before posting them to IRC
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text


def format_slack_message(text: str, users: dict[str, Any]) -> str:
    """
    Strip any color codes coming from IRC, since Slack cannot display them
    The current solution is taken from https://stackoverflow.com/a/970723
    We don't have to worry about encoding >, <, and & here to their
    HTML-escaped equivalents, because Slack's Python client already does this
    for us.

    TODO: Preserve bold and italics (convert to markdown?)
    """

    def nick_replace(match: Match[str]) -> str:
        """
        Replace any IRC nick of the form keur-slack to <@keur> if it's in
        the provided list of Slack display names. To prevent accidental
        conversions, "no-more-slack" will not be converted to "<@no-more>",
        assuming no user has the display name "no-more" in the Workspace.
        """
        nick = match.group(1)
        for user in users.values():
            if nick == user.slack_name:
                return f'<@{nick}>'
        return match.group(0)

    text = re.sub(r'\x03(?:\d{1,2}(?:,\d{1,2})?)?', '', text, flags=re.UNICODE)
    # we can be greedy here; nick is checked against valid list of users
    text = re.sub(r'([^\s]+)-slack', nick_replace, text)
    # remove any @channel or @here
    text = re.sub(r'<!(everyone|channel|here)>', r'<! \1>', text)
    return text


def slack_api(slack_client: SlackClient, *args: Any, **kwargs: Any) -> Any:
    results = slack_client.api_call(*args, **kwargs)
    if results['ok']:
        return results
    else:
        log.err(f'Error calling Slack API: {results}')
        # TODO: Handle this better than exiting
        sys.exit(1)
