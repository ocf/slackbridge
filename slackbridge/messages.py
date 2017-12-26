import functools
import time

from twisted.python import log

# Subtypes of messages we don't want mirrored to IRC
IGNORED_MSG_SUBTYPES = (
    # Joins and leaves are already shown by IRC when the bot joins/leaves, so
    # we don't need these. The leave messages actually are already not shown
    # because the bot exits, then gets the message, so it never gets posted.
    'channel_join',
    'channel_leave',
)


@functools.total_ordering
class SlackMessage:
    def __init__(self, raw_message, bridge_bot):
        self.raw_message = raw_message
        self.bridge_bot = bridge_bot

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
            """Instantiate a new bot user with the user's information"""
            self.bridge_bot.factory.instantiate_bot(self.raw_message['user'])
            return

        user = self.raw_message['user']
        if not isinstance(user, str) or user not in self.bridge_bot.users:
            return

        user_bot = self.bridge_bot.users[user]

        if message_type == 'presence_change':
            self._change_presence(user_bot)
            return

        if 'channel' not in self.raw_message:
            return

        channel_id = self.raw_message['channel']
        if channel_id in self.bridge_bot.channels:
            channel_name = self.bridge_bot.channels[channel_id]['name']
            if message_type == 'message':
                if 'subtype' in self.raw_message:
                    subtype = self.raw_message['subtype']
                    if subtype in IGNORED_MSG_SUBTYPES:
                        return
                    if subtype == 'me_message':
                        return self._irc_me_action(channel_name, user_bot)

                    # TODO: support file uploads here (file_share subtype)

                log.msg('Posting message to IRC')
                self._post_to_irc(channel_name, user_bot)
            elif message_type == 'member_joined_channel':
                user_bot.join(channel_name)
            elif message_type == 'member_left_channel':
                user_bot.leave(channel_name)
            return

    def _change_presence(self, user_bot):
        if self.raw_message['presence'] == 'away':
            user_bot.away('Slack user inactive.')
        elif self.raw_message['presence'] == 'active':
            user_bot.back()

    def _irc_me_action(self, channel_name, user_bot):
        user_bot.post_to_irc(
            user_bot.describe,
            '#' + channel_name,
            self.raw_message['text'],
        )

    def _post_to_irc(self, channel_name, user_bot):
        user_bot.post_to_irc(
            user_bot.msg,
            '#' + channel_name,
            self.raw_message['text'],
        )

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
