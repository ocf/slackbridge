import argparse
import sys
from configparser import ConfigParser

from slackclient import SlackClient
from twisted.internet import reactor
from twisted.internet import ssl
from twisted.python import log

from slackbridge.factories import BridgeBotFactory
from slackbridge.utils import IRC_HOST
from slackbridge.utils import IRC_PORT
from slackbridge.utils import slack_api

BRIDGE_NICKNAME = 'slack-bridge'


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

    # Log everything to stdout, which will be passed to syslog by stdin2syslog
    log.startLogging(sys.stdout)

    # Get all channels from Slack
    # TODO: Remove duplication between here and the user selection part
    # This should just be made into a generic Slack API call method
    log.msg('Requesting list of channels from Slack...')
    results = slack_api(sc, 'channels.list', exclude_archives=1)
    slack_channels = results['channels']

    # Get all users from Slack, but don't select bots, deactivated users, or
    # slackbot to have IRC bots
    log.msg('Requesting list of users from Slack...')
    results = slack_api(sc, 'users.list')
    slack_users = [
        m for m in results['members']
        if not m['is_bot']
        and not m['deleted']
        and m['name'] != 'slackbot'
    ]

    # Main IRC bot thread
    nickserv_pass = conf.get('irc', 'nickserv_pass')
    bridge_factory = BridgeBotFactory(
        sc, BRIDGE_NICKNAME, nickserv_pass, slack_uid,
        slack_channels, slack_users,
    )
    reactor.connectSSL(
        IRC_HOST, IRC_PORT, bridge_factory, ssl.ClientContextFactory()
    )
    reactor.run()


if __name__ == '__main__':
    main()
