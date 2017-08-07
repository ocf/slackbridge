from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log

from slackbridge.bots import BridgeBot


class BotFactory(ReconnectingClientFactory):

    def clientConnectionLost(self, connector, reason):
        log.err('Lost connection.  Reason: {}'.format(reason))
        super().clientConnectionLost(connector, reason)

    def clientConnectionFailed(self, connector, reason):
        log.err('Connection failed. Reason: {}'.format(reason))
        super().clientConnectionFailed(connector, reason)


class BridgeBotFactory(BotFactory):

    def __init__(self, slack_client, nickserv_password, slack_uid, channels):
        self.slack_client = slack_client
        self.slack_uid = slack_uid
        self.nickserv_password = nickserv_password
        self.channels = channels
        self.bot_class = BridgeBot

    def buildProtocol(self, addr):
        p = BridgeBot(self.slack_client, self.nickserv_password,
                      self.slack_uid, self.channels)
        p.factory = self
        self.resetDelay()
        return p


class UserBotFactory(BotFactory):

    def __init__(self):
        pass
