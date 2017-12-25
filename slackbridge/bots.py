import functools
import queue
import re
import time

from twisted.internet.task import LoopingCall
from twisted.python import log
from twisted.words.protocols import irc

import slackbridge.utils as utils

# Subtypes of messages we don't want mirrored to IRC
IGNORED_MSG_SUBTYPES = (
    # Joins and leaves are already shown by IRC when the bot joins/leaves, so
    # we don't need these. The leave messages actually are already not shown
    # because the bot exits, then gets the message, so it never gets posted.
    'channel_join',
    'channel_leave',
)


class IRCBot(irc.IRCClient):
    pass


class BridgeBot(IRCBot):

    @functools.total_ordering
    class SlackMessage:
        def __init__(self, raw_message, bridge_bot):
            self.raw_message = raw_message
            self.channels = bridge_bot.channels
            self.users = bridge_bot.users
            if 'ts' in raw_message:
                self.timestamp = float(raw_message['ts'])
            else:
                self.timestamp = time.time()

        def resolve(self):
            if ('type' not in self.raw_message or
                    'user' not in self.raw_message or
                    'bot_id' in self.raw_message):
                return

            message_type = self.raw_message['type']

            if self.raw_message['type'] == 'team_join':
                self._create_irc_bot(self.raw_message['user'])
                return

            user = self.raw_message['user']
            if not isinstance(user, str) or user not in self.users:
                return

            user_bot = self.users[user]

            if message_type == 'presence_change':
                self._change_presence(user_bot)
                return

            if 'channel' not in self.raw_message:
                return

            channel_id = self.raw_message['channel']
            if channel_id in self.channels:
                channel_name = self.channels[channel_id]['name']
                if message_type == 'message':
                    if 'subtype' in self.raw_message:
                        if self.raw_message['subtype'] in IGNORED_MSG_SUBTYPES:
                            return
                        # TODO: support file uploads here (file_share subtype)

                    log.msg('Posting message to IRC')
                    self._post_to_irc(channel_name, user_bot)
                elif message_type == 'member_joined_channel':
                    self._join_channel(channel_name, user_bot)
                elif message_type == 'member_left_channel':
                    self._part_channel(channel_name, user_bot)
                return

        def _create_irc_bot(self, user):
            IRCBot.slack_users.append(user)
            self.bridge_bot.factory.instantiate_bot(user)

        def _change_presence(self, user_bot):
            if self.raw_message['presence'] == 'away':
                user_bot.away('Slack user inactive.')
            elif self.raw_message['presence'] == 'active':
                user_bot.back()

        def _post_to_irc(self, channel_name, user_bot):
            user_bot.post_to_irc(
                '#' + channel_name, self.raw_message['text'])

        def _join_channel(self, channel_name, user_bot):
            user_bot.join_channel(channel_name)

        def _part_channel(self, channel_name, user_bot):
            user_bot.part_channel(channel_name)

        # For PriorityQueue to order by timestamp, override comparisons.
        # @total_ordering generates the other comparisons given the two below.
        def __lt__(self, other):
            if not hasattr(other, 'timestamp'):
                return NotImplemented
            return self.timestamp < other.timestamp

        def __eq__(self, other):
            if not hasattr(other, 'timestamp'):
                return NotImplemented
            return self.timestamp == other.timestamp

    def __init__(self, sc, bridge_nick, nickserv_pw, slack_uid, channels,
                 user_bots):
        self.sc = sc
        self.user_bots = user_bots
        self.nickserv_password = nickserv_pw
        self.slack_uid = slack_uid
        self.users = {bot.user_id: bot for bot in user_bots}
        self.channels = {channel['id']: channel for channel in channels}
        self.channel_name_uid_map = {channel['name']: channel['id']
                                     for channel in channels}
        self.nickname = bridge_nick
        self.message_queue = queue.PriorityQueue()

        self.rtm_connect()

        log.msg('Connected successfully to Slack RTM')

        # Create a looping call to poll Slack for updates
        rtm_loop = LoopingCall(self.check_slack_rtm)
        # Slack's rate limit is 1 request per second, so set this to something
        # greater than or equal to that to avoid problems
        rtm_loop.start(1)

        # Create another looping call which acts on messages in the queue
        message_loop = LoopingCall(self.empty_queue)
        message_loop.start(0.5)

    def rtm_connect(self):
        # Attempt to connect to Slack RTM
        while not self.sc.rtm_connect():
            log.err('Could not connect to Slack RTM, check token/rate limits')
            time.sleep(5)

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
            message_list = self.sc.rtm_read()
        except TimeoutError:
            log.err('Retrieving message from Slack RTM timed out')
            self.rtm_connect()
            return

        if not message_list:
            return

        for message in message_list:
            log.msg(message)

            if 'type' in message:
                message_obj = self.SlackMessage(message, self)
                self.message_queue.put(message_obj)

    def empty_queue(self):
        while not self.message_queue.empty():
            message = self.message_queue.get()
            message.resolve()

    # Implements the IRCClient event handler of the same name,
    # which gets called when the topic changes, or when
    # a channel is entered for the first time.
    def topicUpdated(self, user, channel, new_topic):
        channel_uid = self.channel_name_uid_map[channel[1:]]
        last_topic = self.channels[channel_uid]['topic']['value']
        if new_topic != last_topic:
            self.sc.api_call(
                'channels.setTopic',
                channel=channel_uid,
                topic=new_topic
            )


class UserBot(IRCBot):

    def __init__(self, nickname, realname, user_id, channels,
                 target_group, nickserv_pw):
        self.nickname = '{}-slack'.format(utils.strip_nick(nickname))
        self.realname = realname
        self.user_id = user_id
        self.channels = channels
        self.nickserv_password = nickserv_pw
        self.target_group_nick = target_group

    def log(self, method, message):
        full_message = '[{}]: {}'.format(self.nickname, message)
        return method(full_message)

    def signedOn(self):
        # If already registered, auth in
        self.msg('NickServ', 'IDENTIFY {}'.format(self.nickserv_password))
        # And if not, register for the first time
        self.msg('NickServ', 'GROUP {} {}'.format(self.target_group_nick,
                                                  self.nickserv_password))
        for channel in self.channels:
            self.log(log.msg, 'Joining #{}'.format(channel['name']))
            self.join_channel(channel['name'])

        self.away('Default away for startup.')

    def join_channel(self, channel_name):
        self.join('#{}'.format(channel_name))

    def part_channel(self, channel_name):
        self.leave('#{}'.format(channel_name))

    def post_to_irc(self, channel, message):
        log.msg('User bot posting message to IRC')
        self.msg(channel, self._format_message(message))

    def _format_message(self, message):
        match_ids = re.findall(r'(<\@([A-Z0-9]{9,})\>)', message)
        # Avoid duplicate searches for multiple users mentions
        # in the same Slack message.
        for replace, uid in set(match_ids):
            user_info = next(
                (user for user in self.slack_users if user['id'] == uid),
                None,
            )
            if user_info:
                target_nick = '{}-slack'.format(
                    utils.strip_nick(user_info['name']),
                )
                message = message.replace(replace, target_nick)
        return message
