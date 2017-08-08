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
        self.slack_channels = channels

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

        for channel in self.slack_channels:
            log.msg('Joining #{}'.format(channel['name']))
            self.join('#{}'.format(channel['name']))

    def privmsg(self, user, channel, message):
        # user is like 'jvperrin!Jason@fireball.ocf.berkeley.edu' so only
        # take the part before the exclamation mark for the Slack display name
        assert user.count('!') == 1
        user_nick, _ = user.split('!')

        # Don't post to Slack if it came from a Slack bot
        if not user_nick.endswith('-slack'):
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
        message = self.sc.rtm_read()

        # TODO: This is horrible and should be cleaned up a lot
        if message:
            message = message[0]
            log.msg(message)
            if message['type'] == 'message' and 'bot_id' not in message:
                for user_bot in self.user_bots:
                    if user_bot.user_id == message['user']:
                        for channel in self.slack_channels:
                            if channel['id'] == message['channel']:
                                user_bot.post_to_irc(
                                    '#' + channel['name'], message['text'])


class UserBot(IRCBot):

    def __init__(self, nickname, user_id, channels):
        self.nickname = '{}-slack'.format(nickname)
        self.user_id = user_id
        self.channels = channels
        # TODO: Add real names

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
