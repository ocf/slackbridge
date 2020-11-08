from __future__ import annotations

import argparse
import sys
from configparser import ConfigParser

from slackclient import SlackClient
from twisted.internet import reactor
from twisted.internet import ssl
from twisted.python import log

from slackbridge.bots import IRCBot
from slackbridge.factories import BridgeBotFactory
from slackbridge.utils import IRC_HOST
from slackbridge.utils import IRC_PORT
from slackbridge.utils import slack_api

BRIDGE_NICKNAME = 'slack-bridge'


def main() -> None:
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

    # Initialize Slack Client
    sc = SlackClient(slack_token)

    # Set IRCBot class variables to avoid
    # senselessly passing around variables
    IRCBot.slack_token = slack_token

    # Log everything to stdout, which will be passed to syslog by stdin2syslog
    log.startLogging(sys.stdout)

    # Get all channels from Slack
    log.msg('Requesting list of channels from Slack...')
    results = slack_api(
        sc,
        'conversations.list',
        limit=500,
        exclude_archived=True,
    )
    slack_channels = results['channels']

    # Get a proper list of members for each channel. We're forced to do this by
    # Slack API changes that don't return the full member list:
    # https://api.slack.com/changelog/2017-10-members-array-truncating
    for channel in slack_channels:
        # Querying Slack for members of an empty channel causes an error
        if channel['num_members'] == 0:
            channel['members'] = []
            continue

        results = slack_api(
            sc,
            'conversations.members',
            limit=500,
            channel=channel['id'],
        )
        channel['members'] = results['members']
        while results['response_metadata']['next_cursor']:
            results = slack_api(
                sc,
                'conversations.members',
                limit=500,
                channel=channel['id'],
                cursor=results['response_metadata']['next_cursor'],
            )
            channel['members'] += results['members']

        # Make sure all members have been added successfully
        assert(len(channel['members']) >= channel['num_members'])

    # Get all users from Slack, but don't select bots, deactivated users, or
    # slackbot, since they don't need IRC bots (they aren't users)
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
        IRC_HOST, IRC_PORT, bridge_factory, ssl.ClientContextFactory(),
    )
    reactor.run()


if __name__ == '__main__':
    main()
