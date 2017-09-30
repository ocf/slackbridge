import time

from twisted.internet.task import LoopingCall
from twisted.python import log
from twisted.words.protocols import irc

import slackbridge.utils as utils


class IRCBot(irc.IRCClient):
    pass


class BridgeBot(IRCBot):
    nickname = 'slack-bridge'

    def __init__(self, sc, nickserv_pw, slack_uid, channels, user_bots):
        self.topics = {}
        self.user_bots = user_bots
        self.sc = sc
        self.nickserv_password = nickserv_pw
        self.slack_uid = slack_uid
        self.users = {bot.user_id: bot for bot in user_bots}
        self.channels = {channel['id']: channel for channel in channels}

        # Attempt to connect to Slack RTM
        while not self.sc.rtm_connect():
            log.err('Could not connect to Slack RTM, check token/rate limits')
            time.sleep(5)

        log.msg('Connected successfully to Slack RTM')

        # Create a looping call to poll Slack for updates
        loop = LoopingCall(self.check_slack_rtm)
        # Slack's rate limit is 1 request per second, so set this to something
        # greater than or equal to that to avoid problems
        loop.start(1)

    def signedOn(self):
        self.msg('NickServ', 'identify {}'.format(self.nickserv_password))
        log.msg('Authenticated with NickServ')

        for channel in self.channels.values():
            log.msg('Joining #{}'.format(channel['name']))
            self.join('#{}'.format(channel['name']))

    def privmsg(self, user, channel, message):
        # user is like 'jvperrin!Jason@fireball.ocf.berkeley.edu' so only
        # take the part before the exclamation mark for the Slack display name
        assert user.count('!') == 1
        user_nick, _ = user.split('!')

        # Don't post to Slack if it came from a Slack bot
        if '-slack' not in user_nick and user_nick != 'defaultnick':
            self.post_to_slack(user_nick, channel, message)

    def post_to_slack(self, user, channel, message):
        self.sc.api_call(
            'chat.postMessage',
            channel=channel,
            text=message,
            as_user=False,
            username=user,
            icon_url=utils.user_to_gravatar(user),
        )

    def check_slack_rtm(self):
        try:
            message = self.sc.rtm_read()
        except TimeoutError:
            log.err('Retrieving message from Slack RTM timed out')
            message = None

        if not message:
            return

        message = message[0]
        log.msg(message)

        if 'type' not in message:
            return

        if (message['type'] == 'presence_change' and
                message['user'] in self.users):
            user_bot = self.users[message['user']]
            if message['presence'] == 'away':
                user_bot.away('Slack user inactive.')
            elif message['presence'] == 'active':
                user_bot.back()
            return

        if (message['type'] != 'message' or
                'user' not in message or
                'bot_id' in message):
            return

        if (message['user'] in self.users and
                message['channel'] in self.channels):
            user_bot = self.users[message['user']]
            channel = self.channels[message['channel']]
            return user_bot.post_to_irc('#' + channel['name'], message['text'])


class UserBot(IRCBot):

    def __init__(self, nickname, realname, user_id, channels):
        self.nickname = '{}-slack'.format(utils.strip_nick(nickname))
        self.realname = realname
        self.user_id = user_id
        self.channels = channels

    def log(self, method, message):
        full_message = '[{}]: {}'.format(self.nickname, message)
        return method(full_message)

    def signedOn(self):
        # TODO: Add NickServ authentication for these bots too?
        for channel in self.channels:
            self.log(log.msg, 'Joining #{}'.format(channel['name']))
            self.join('#{}'.format(channel['name']))

    def post_to_irc(self, channel, message):
        self.msg(channel, message)
