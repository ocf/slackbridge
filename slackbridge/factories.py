from twisted.internet import reactor
from twisted.internet import ssl
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log

from slackbridge.bots import BridgeBot
from slackbridge.bots import IRCBot
from slackbridge.bots import UserBot
from slackbridge.utils import IRC_HOST
from slackbridge.utils import IRC_PORT


class BotFactory(ReconnectingClientFactory):

    def clientConnectionLost(self, connector, reason):
        log.err('Lost connection.  Reason: {}'.format(reason))
        super().clientConnectionLost(connector, reason)

    def clientConnectionFailed(self, connector, reason):
        log.err('Connection failed. Reason: {}'.format(reason))
        super().clientConnectionFailed(connector, reason)


class BridgeBotFactory(BotFactory):

    def __init__(self, slack_client, bridge_nick, nickserv_pw, slack_uid,
                 channels, users):
        self.slack_client = slack_client
        self.slack_uid = slack_uid
        self.bridge_nickname = bridge_nick
        self.nickserv_password = nickserv_pw
        self.bot_class = BridgeBot

        # Give all bots access to the Slack channel and user list
        IRCBot.channels = {
            channel['id']: channel for channel in channels
        }
        IRCBot.channel_name_to_uid = {
            channel['name']: channel['id'] for channel in channels
        }

        # Create individual user bots with their own connections to the IRC
        # server and their own nicknames
        for user in users:
            self.instantiate_bot(user)

    def buildProtocol(self, addr):
        p = BridgeBot(
            self.slack_client,
            self.bridge_nickname,
            self.nickserv_password,
            self.slack_uid,
        )
        p.factory = self
        self.resetDelay()
        return p

    def add_user_bot(self, user_bot):
        IRCBot.users[user_bot.user_id] = user_bot

    def instantiate_bot(self, user):
        user_factory = UserBotFactory(
            self,
            user,
            self.bridge_nickname,
            self.nickserv_password,
        )
        reactor.connectSSL(
            IRC_HOST, IRC_PORT, user_factory, ssl.ClientContextFactory()
        )


class UserBotFactory(BotFactory):

    def __init__(self, bridge_bot_factory, slack_user, target_group,
                 nickserv_pw):
        self.bridge_bot_factory = bridge_bot_factory
        self.slack_user = slack_user
        self.joined_channels = []
        self.target_group_nick = target_group
        self.nickserv_password = nickserv_pw

        for channel in IRCBot.channels.values():
            if slack_user['id'] in channel['members']:
                self.joined_channels.append(channel['name'])

    def buildProtocol(self, addr):
        p = UserBot(
            self.slack_user['name'],
            self.slack_user['real_name'],
            self.slack_user['id'],
            self.joined_channels,
            self.target_group_nick,
            self.nickserv_password,
        )
        p.factory = self
        self.bridge_bot_factory.add_user_bot(p)
        self.resetDelay()
        return p
