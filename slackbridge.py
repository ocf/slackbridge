#!/usr/bin/env python3
"""Bridge between IRC and Slack"""
import argparse
import hashlib
import sys
from configparser import ConfigParser

from ocflib.misc.mail import send_problem_report
from slackclient import SlackClient
from twisted.internet import reactor
from twisted.internet import ssl
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log
from twisted.words.protocols import irc

IRC_HOST = 'dev-irc.ocf.berkeley.edu'
IRC_PORT = 6697
IRC_NICKNAME = 'slack-bridge'
GRAVATAR_URL = 'http://www.gravatar.com/avatar/{}?s=48&r=any&default=identicon'


class BotFactory(ReconnectingClientFactory):

    def buildProtocol(self, addr):
        p = BridgeBot(self.slack_client, self.nickserv_password, self.channels)
        p.factory = self
        self.resetDelay()
        return p

    def clientConnectionLost(self, connector, reason):
        log.msg('Lost connection.  Reason: {}'.format(reason))
        super().clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        log.msg('Connection failed. Reason: {}'.format(reason))
        super().clientConnectionFailed(self, connector, reason)


class BridgeBotFactory(ReconnectingClientFactory):

    def __init__(self, slack_client, nickserv_password, channels):
        self.slack_client = slack_client
        self.nickserv_password = nickserv_password
        self.channels = channels
        self.bot_class = BridgeBot

    def buildProtocol(self, addr):
        p = BridgeBot(self.slack_client, self.nickserv_password, self.channels)
        p.factory = self
        self.resetDelay()
        return p

    def clientConnectionLost(self, connector, reason):
        log.msg('Lost connection.  Reason: {}'.format(reason))
        super().clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        log.msg('Connection failed. Reason: {}'.format(reason))
        super().clientConnectionFailed(self, connector, reason)


class UserBot(irc.IRCClient):
    # Not implemented yet, but this will be so that there is a bot per Slack
    # user, like with the current bridge
    pass


class BridgeBot(irc.IRCClient):
    nickname = IRC_NICKNAME

    def __init__(self, slack_client, nickserv_password, user, channels):
        self.topics = {}
        self.sc = slack_client
        self.nickserv_password = nickserv_password
        self.slack_user = user
        self.slack_channels = channels

    def connectionLost(self, reason):
        log.msg('Connection lost with IRC server: {}'.format(reason))
        super().connectionLost(self, reason)

    def signedOn(self):
        self.msg('NickServ', 'identify {}'.format(self.nickserv_password))
        log.msg('Authenticated with NickServ')

        for channel in self.slack_channels:
            log.msg('Joining #{}'.format(channel))
            self.join('#{}'.format(channel))

    def privmsg(self, user, channel, message):
        # user is like 'jvperrin!Jason@fireball.ocf.berkeley.edu' so only
        # take the part before the exclamation mark for the Slack display name
        assert user.count('!') == 1
        nickname, _ = user.split('!')

        self.post_to_slack(nickname, channel, message)

    def post_to_slack(self, user, channel, message):
        email_hash = hashlib.md5()
        email = '{}@ocf.berkeley.edu'.format(user)
        email_hash.update(email.encode())
        user_icon = GRAVATAR_URL.format(email_hash.hexdigest())

        self.sc.api_call(
            'chat.postMessage',
            channel=channel,
            text=message,
            as_user=False,
            username=user,
            icon_url=user_icon,
        )

    def check_slack_rtm(self):
        message = self.sc.rtm_read()

        if message:
            log.msg(message)


def main():
    parser = argparse.ArgumentParser(
        description='OCF IRC to Slack bridge',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '-c',
        '--config',
        default='/etc/ocf-slackbridge/slackbridge.conf',
        help='Config file to read from.',
    )
    args = parser.parse_args()

    conf = ConfigParser()
    conf.read(args.config)

    # Slack configuration
    slack_token = conf.get('slack', 'token')
    slack_uid = conf.get('slack', 'user')
    sc = SlackClient(slack_token)

    # Get all channels from Slack
    # TODO: Remove duplication between here and the user selection part
    # This should just be made into a generic Slack API call method
    results = sc.api_call('channels.list', exclude_archived=1)
    if results['ok']:
        channels = results['channels']
        slack_channel_names = [c['name'] for c in channels]
    else:
        send_problem_report('Error fetching channels from Slack API')
        sys.exit(1)

    # Get all users from Slack
    # results = sc.api_call('users.list')
    #  if results['ok']:
    #     users = [m for m in results['members'] if not m['is_bot'] and not
    #              m['deleted'] and m['name'] != 'slackbot']
    #  else:
    #     send_problem_report('Error fetching users from Slack API')
    #     sys.exit(1)

    log.startLogging(sys.stdout)

    # Main IRC bot thread
    nickserv_pass = conf.get('irc', 'nickserv_pass')
    bridge_factory = BridgeBotFactory(
        sc, nickserv_pass, slack_uid, slack_channel_names)
    reactor.connectSSL(IRC_HOST, IRC_PORT, bridge_factory,
                       ssl.ClientContextFactory())
    reactor.run()


if __name__ == '__main__':
    main()
