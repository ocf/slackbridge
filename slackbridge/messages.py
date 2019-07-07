from __future__ import annotations

import functools
import os
import re
import time
from typing import Any
from typing import Dict
from typing import List
from typing import TYPE_CHECKING

import requests
from twisted.python import log

if TYPE_CHECKING:
    from slackbridge.bots import BridgeBot
    from slackbridge.bots import UserBot


# Subtypes of messages we don't want mirrored to IRC
IGNORED_MSG_SUBTYPES = (
    # Joins and leaves are already shown by IRC when the bot joins/leaves, so
    # we don't need these. The leave messages actually are already not shown
    # because the bot exits, then gets the message, so it never gets posted.
    'channel_join',
    'channel_leave',
)

FILEHOST = 'https://fluffy.cc'


@functools.total_ordering
class SlackMessage:
    def __init__(self, raw_message: Dict[str, Any], bridge_bot: BridgeBot):
        self.raw_message = raw_message
        self.bridge_bot = bridge_bot
        self.deferred = False

        if 'ts' in raw_message:
            self.timestamp = float(raw_message['ts'])
        else:
            self.timestamp = time.time()

    def resolve(self) -> None:
        if (
            'type' not in self.raw_message or
            'user' not in self.raw_message or
            self.is_bot_user()
        ):
            return

        message_type = self.raw_message['type']
        user = self.raw_message['user']

        if message_type == 'team_join':
            """Instantiate a new bot user with the user's information"""
            self.bridge_bot.factory.instantiate_bot(user)
            return

        if not isinstance(user, str) or user not in self.bridge_bot.users:
            return

        user_bot = self.bridge_bot.users[user]

        if message_type == 'presence_change':
            self._change_presence(user_bot)
            return

        channel_id = self.raw_message.get('channel')
        if not channel_id or not isinstance(channel_id, str):
            return

        if channel_id[0] == 'D':  # DM channels start with a D
            if not user_bot.im_id:
                user_bot.im_id = channel_id

            if 'text' in self.raw_message:
                match = re.search('^(([^:]+):).*$', self.raw_message['text'])
                if match:
                    rcpt = match.group(2)

                    if rcpt in self.bridge_bot.irc_users and self.deferred:
                        irc_user = self.bridge_bot.irc_users[rcpt]
                        if irc_user.authenticated:

                            msg = self.raw_message['text']
                            rcpt_quoted = match.group(1)
                            msg = msg.replace(rcpt_quoted, '', 1).strip()
                            self.raw_message['text'] = msg

                            self._post_pm_to_irc(rcpt, user_bot)
                        else:

                            resp = 'Error: ' + rcpt + ' is ' \
                                'either not online or not authenticated ' \
                                'with NickServ. ' \
                                'Message(s) were not delivered.'

                            self.bridge_bot.post_to_slack(
                                self.bridge_bot.nickname,
                                channel_id,
                                resp, False,
                            )
                    else:
                        # Defer message and attempt to authenticate user
                        # Afterwards this message is re-resolved
                        self.deferred = True

                        if rcpt not in self.bridge_bot.irc_users:
                            self.bridge_bot.irc_users[rcpt] = IRCUser()

                        self.bridge_bot.irc_users[rcpt].add_message(self)

                        self.bridge_bot.authenticate(rcpt)

                else:

                    resp = 'Please message an IRC user ' \
                        'with [username]: [message] '

                    self.bridge_bot.post_to_slack(
                        self.bridge_bot.nickname,
                        channel_id,
                        resp, False,
                    )

        elif channel_id in self.bridge_bot.channels:
            channel_name = self.bridge_bot.channels[channel_id]['name']
            if message_type == 'message':
                if 'subtype' in self.raw_message:
                    subtype = self.raw_message['subtype']
                    if subtype in IGNORED_MSG_SUBTYPES:
                        return
                    if subtype == 'me_message':
                        return self._irc_me_action(
                            channel_name,
                            user_bot,
                            self.raw_message['text'],
                        )
                for file in self.raw_message.get('files', []):
                    self._post_to_fluffy(
                        channel_name,
                        user_bot,
                        file,
                    )

                log.msg('Posting message to IRC')
                self._post_to_irc(channel_name, user_bot)
            elif message_type == 'member_joined_channel':
                user_bot.join(channel_name)
            elif message_type == 'member_left_channel':
                user_bot.leave(channel_name)
            return

    def is_bot_user(self) -> bool:
        """Sometimes bot_id is not included and other
        times it is passed as None. Checks both cases."""
        return (
            'bot_id' in self.raw_message and
            self.raw_message['bot_id'] is not None
        )

    def _change_presence(self, user_bot: UserBot) -> None:
        if self.raw_message['presence'] == 'away':
            user_bot.away('Slack user inactive.')
        elif self.raw_message['presence'] == 'active':
            user_bot.back()

    def _irc_me_action(
        self,
        channel_name: str,
        user_bot: UserBot,
        action: str,
    ) -> None:
        user_bot.post_to_irc(
            user_bot.describe,
            '#' + channel_name,
            action,
        )

    def _post_to_fluffy(
        self,
        channel_name: str,
        user_bot: UserBot,
        file_data: Dict[str, Any],
    ) -> None:
        # Adapted from https://api.slack.com/tutorials/working-with-files
        auth = {
            'Authorization': 'Bearer {}'.format(
                self.bridge_bot.slack_token,
            ),
        }
        r = requests.get(
            file_data['url_private'],
            headers=auth,
            stream=True,
        )
        if r.status_code != 200:
            log.err(
                'Could not GET image from: {}'.format(
                    file_data['url_private'],
                ),
            )
            return

        # Ensure file has an extension as this is necessary
        # for fluffy to give a direct link in the browser.
        filename = file_data['name']
        if not os.path.splitext(filename)[1]:
            filename += '.' + file_data['filetype']

        # Decompress file data and upload the file data as
        # it is streamed.
        r.raw.decode_content = True
        r = requests.post(
            FILEHOST + '/upload?json',
            files={'file': (filename, r.raw)},
        )
        if (
            r.status_code == 413 and
            'thumb_1024' in file_data and
            file_data['url_private'] != file_data['thumb_1024']
        ):
            # file is too large, so force the use of the 1024 thumb
            # Note: this only works with images, other files, for instance
            # videos, do not have the thumb_1024 attribute
            file_data['url_private'] = file_data['thumb_1024']
            return self._post_to_fluffy(
                channel_name,
                user_bot,
                file_data,
            )
        elif r.status_code != 200:
            log.err(
                'Failed to upload (status code {}):'.format(
                    r.status_code,
                ),
            )
            return

        resp = r.json()
        if not resp['success']:
            log.err(resp['error'])
            return

        upload = resp['uploaded_files'][filename]
        location = upload['paste'] or upload['raw']
        self._irc_me_action(
            channel_name,
            user_bot,
            'uploaded a file: ' + location,
        )

    def _post_to_irc(self, channel_name: str, user_bot: UserBot) -> None:
        user_bot.post_to_irc(
            user_bot.msg,
            '#' + channel_name,
            self.raw_message['text'],
        )

    def _post_pm_to_irc(self, irc_recipient: str, user_bot: UserBot) -> None:
        user_bot.post_to_irc(
            user_bot.msg,
            irc_recipient,
            self.raw_message['text'],
        )

    # For PriorityQueue to order by timestamp, override comparisons.
    # @total_ordering generates the other comparisons given the two below.
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SlackMessage):
            return NotImplemented
        return self.timestamp < other.timestamp

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SlackMessage):
            return NotImplemented
        return self.timestamp == other.timestamp


class IRCUser:

    def __init__(self, authenticated: bool = False):
        self.authenticated = authenticated
        self.messages: List[SlackMessage] = []

    def add_message(self, message: SlackMessage) -> None:
        self.messages.append(message)
