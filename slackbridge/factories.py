from twisted.internet import reactor
from twisted.internet import ssl
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log

from slackbridge.bots import BridgeBot
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

    def __init__(self, slack_client, nickserv_pw, slack_uid, channels, users):
        self.slack_client = slack_client
        self.slack_uid = slack_uid
        self.nickserv_password = nickserv_pw
        self.channels = channels
        self.bot_class = BridgeBot
        self.user_bots = []

        # Create individual user bots with their own connections to the IRC
        # server and their own nicknames
        for user in users:
            user_factory = UserBotFactory(
                self, user, channels,
            )
            reactor.connectSSL(
                IRC_HOST, IRC_PORT, user_factory, ssl.ClientContextFactory()
            )

    def buildProtocol(self, addr):
        p = BridgeBot(self.slack_client, self.nickserv_password,
                      self.slack_uid, self.channels, self.user_bots)
        p.factory = self
        self.resetDelay()
        return p

    def add_user_bot(self, user_bot):
        self.user_bots.append(user_bot)


class UserBotFactory(BotFactory):

    def __init__(self, bridge_bot_factory, slack_user, channels):
        self.bridge_bot_factory = bridge_bot_factory
        self.slack_user = slack_user
        # TODO: Only join channels the user is in instead of all channels
        self.channels = channels

    def buildProtocol(self, addr):
        p = UserBot(self.slack_user['name'],
                    self.slack_user['id'], self.channels)
        p.factory = self
        self.bridge_bot_factory.add_user_bot(p)
        self.resetDelay()
        return p
