from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List

from slackclient import SlackClient
from twisted.internet import reactor
from twisted.internet import ssl
from twisted.internet.interfaces import IAddress
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log
from twisted.python.failure import Failure

from slackbridge.bots import BridgeBot
from slackbridge.bots import IRCBot
from slackbridge.bots import UserBot
from slackbridge.utils import IRC_HOST
from slackbridge.utils import IRC_PORT


class BotFactory(ReconnectingClientFactory):

    def clientConnectionLost(self, connector: Any, reason: Failure) -> None:
        log.err(f'Lost connection.  Reason: {reason}')
        super().clientConnectionLost(connector, reason)

    def clientConnectionFailed(self, connector: Any, reason: Failure) -> None:
        log.err(f'Connection failed. Reason: {reason}')
        super().clientConnectionFailed(connector, reason)


class BridgeBotFactory(BotFactory):

    def __init__(
        self,
        slack_client: SlackClient,
        bridge_nick: str,
        nickserv_pw: str,
        slack_uid: str,
        channels: List[Dict[str, Any]],
        users: List[Dict[str, Any]],
    ):
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

    def buildProtocol(self, addr: IAddress) -> BridgeBot:
        p = BridgeBot(
            self.slack_client,
            self.bridge_nickname,
            self.nickserv_password,
            self.slack_uid,
        )
        IRCBot.bots[self.slack_uid] = p
        p.factory = self
        self.resetDelay()
        return p

    def add_user_bot(self, user_bot: UserBot) -> None:
        IRCBot.users[user_bot.user_id] = user_bot

    def instantiate_bot(self, user: Dict[str, Any]) -> None:
        user_factory = UserBotFactory(
            self.slack_client,
            self,
            user,
            self.bridge_nickname,
            self.nickserv_password,
        )
        reactor.connectSSL(
            IRC_HOST, IRC_PORT, user_factory, ssl.ClientContextFactory(),
        )


class UserBotFactory(BotFactory):

    def __init__(
        self,
        slack_client: SlackClient,
        bridge_bot_factory: BridgeBotFactory,
        slack_user: Dict[str, Any],
        target_group: str,
        nickserv_pw: str,
    ):
        self.slack_client = slack_client
        self.bridge_bot_factory = bridge_bot_factory
        self.slack_user = slack_user
        self.joined_channels: List[str] = []
        self.target_group_nick = target_group
        self.nickserv_password = nickserv_pw

        for channel in IRCBot.channels.values():
            if slack_user['id'] in channel['members']:
                self.joined_channels.append(channel['name'])

    def buildProtocol(self, addr: IAddress) -> UserBot:
        p = UserBot(
            self.slack_client,
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
