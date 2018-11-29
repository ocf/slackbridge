import queue
import time

from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.python import log
from twisted.words.protocols import irc

import slackbridge.utils as utils
from slackbridge.messages import IRCUser
from slackbridge.messages import SlackMessage


class IRCBot(irc.IRCClient):
    # Global-ish lookup tables for users/channels by id to make it so this
    # information is not passed around everywhere and to not have to make a
    # Slack API call each time this information is wanted, since it doesn't
    # change often and can be updated by events.
    channels = {}
    channel_name_to_uid = {}
    users = {}
    # Used to download slack files
    slack_token = None
    sc = None
    # Used to store lookup and deferred private messages
    irc_users = {}

    def __init__(self, sc, nickname, nickserv_pw):
        self.sc = sc
        self.nickname = nickname
        self.nickserv_password = nickserv_pw

    def post_to_slack(self, user, channel, message, unparsed_nick=True):
        if unparsed_nick:
            nick = utils.nick_from_irc_user(user)
        else:
            nick = user

        # Don't post to Slack if it came from a Slack bot
        if '-slack' not in nick and nick != 'defaultnick':
            log.msg(self.sc.api_call(
                'chat.postMessage',
                channel=channel,
                text=utils.format_slack_message(message, IRCBot.users),
                as_user=False,
                username=nick,
                icon_url=utils.user_to_gravatar(nick),
            ))


class BridgeBot(IRCBot):

    def __init__(self, sc, bridge_nick, nickserv_pw, slack_uid):
        self.slack_uid = slack_uid
        self.message_queue = queue.PriorityQueue()

        super().__init__(sc, bridge_nick, nickserv_pw)

        self.rtm_connect()

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
        while not self.sc.rtm_connect(auto_reconnect=True):
            log.err('Could not connect to Slack RTM, check token/rate limits')
            time.sleep(5)
        log.msg('Connected successfully to Slack RTM')

    def signedOn(self):
        self.msg('NickServ', 'identify {}'.format(self.nickserv_password))
        log.msg('Authenticated with NickServ')

        for channel in self.channels.values():
            log.msg('Joining #{}'.format(channel['name']))
            self.join('#{}'.format(channel['name']))

    def privmsg(self, user, channel, message):
        self.post_to_slack(user, channel, message)

    def action(self, user, channel, message):
        self.post_to_slack(user, channel, '_{}_'.format(message))

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
                self.message_queue.put(SlackMessage(message, self))

    def empty_queue(self):
        while not self.message_queue.empty():
            message = self.message_queue.get()
            message.resolve()

    # Implements the IRCClient event handler of the same name,
    # which gets called when the topic changes, or when
    # a channel is entered for the first time.
    def topicUpdated(self, user, channel, new_topic):
        channel_uid = self.channel_name_to_uid[channel[1:]]
        last_topic = self.channels[channel_uid]['topic']['value']
        if new_topic != last_topic:
            self.sc.api_call(
                'channels.setTopic',
                channel=channel_uid,
                topic=new_topic
            )

    def irc_330(self, prefix, params):
        """
        A 330-prefix response after a WHOIS [user] is sent
        if [user] is registered AND authenticated.

        Format of params:
        [Querier, user, authenticated_name, 'is logged in as']
        ['slack-bridge', 'jaw', 'jaw', 'is logged in as']
        """
        current_nickname = params[1]
        authenticated_name = params[2]

        self.verify_auth(current_nickname, authenticated_name)

    def irc_RPL_ENDOFWHOIS(self, prefix, params):
        """
        RPL_ENDOFWHOIS signifies end of a WHOIS list for [user].

        Format of params:
        [Querier, user]
        ['slack-bridge', 'jaw', 'End of /WHOIS list.']
        """
        user = params[1]

        self.end_whois(user)

    def userRenamed(self, user, newname):
        self.deauthenticate(user)
        self.deauthenticate(newname)

    def userLeft(self, user, channel):
        self.deauthenticate(user)

    def userQuit(self, user, quitMessage):
        self.deauthenticate(user)

    def userKicked(self, user, channel, kicker, message):
        self.deauthenticate(user)

    def deauthenticate(self, user):
        if user in self.irc_users:
            self.irc_users.pop(user)

    def authenticate(self, user):
        if user not in self.irc_users:
            self.irc_users[user] = IRCUser()
        else:
            self.irc_users[user].authenticated = False
        self.whois(user)

    def verify_auth(self, current_nickname, authenticated_name):
        user = self.irc_users[current_nickname]

        user.authenticated = (current_nickname == authenticated_name)

    def end_whois(self, user):
        message_copy = self.irc_users[user].messages
        for message in message_copy:
            message.resolve()
            self.irc_users[user].messages.remove(message)


class UserBot(IRCBot):

    def __init__(self, sc, nickname, realname, user_id, joined_channels,
                 target_group, nickserv_pw):
        intended_nickname = '{}-slack'.format(utils.strip_nick(nickname))

        self.sc = sc
        self.slack_name = nickname
        self.intended_nickname = intended_nickname
        self.realname = realname
        self.user_id = user_id
        self.joined_channels = joined_channels
        self.target_group_nick = target_group
        self.im_id = None

        super().__init__(sc, intended_nickname, nickserv_pw)

    def log(self, method, message):
        full_message = '[{}]: {}'.format(self.nickname, message)
        return method(full_message)

    def signedOn(self):
        self.nickserv_auth()

        for channel_name in self.joined_channels:
            self.log(log.msg, 'Joining #{}'.format(channel_name))
            self.join(channel_name)

        self.away('Default away for startup.')

    def nickserv_auth(self):
        if self.nickname == self.intended_nickname:
            # If already registered, authenticate yourself to Nickserv
            self.msg('NickServ', 'IDENTIFY {}'.format(self.nickserv_password))

            # And if not, register for the first time,
            self.msg('NickServ', 'GROUP {} {}'.format(
                self.target_group_nick,
                self.nickserv_password,
            ))

    def privmsg(self, user, channel, message):
        """
        Handler if a private message is received
        by an IRC user bot. In IRC, this is when
        the channel is a username.

        Example:
        [john]: /msg ocfstaffer-slack hello

        user = "john"
        channel = "ocfstaffer-slack"
        message = "hello"
        """
        if channel == self.nickname:
            if not self.im_id:
                im_channel = self.sc.api_call(
                    'im.open',
                    user=self.user_id,
                    return_im=True
                )
                self.im_id = im_channel['channel']['id']

            nick = utils.nick_from_irc_user(user)
            self.post_to_slack(user, self.im_id, nick + ': ' + message)

    def setNick(self, nickname):
        """
        Called whenever the client wants to set a nickname,
        such as on startup or if there's a collision.
        """
        super().setNick(nickname)
        self.nickserv_auth()

    def nickChanged(self, nick):
        """Called when a nickname is successfully changed."""
        super().nickChanged(nick)
        if nick != self.intended_nickname:
            self.log(
                log.msg,
                'Attempting to change nick to {} in 10 seconds.'.format(
                    self.intended_nickname,
                ),
            )
            reactor.callLater(10, self.setNick, self.intended_nickname)

    def joined(self, channel_name):
        """Called by twisted when a channel has been joined"""
        if channel_name not in self.joined_channels:
            self.joined_channels.append(channel_name)

    def left(self, channel_name):
        """Called by twisted when a channel has been left"""
        if channel_name in self.joined_channels:
            self.joined_channels.remove(channel_name)

    def post_to_irc(self, method, channel, message):
        log.msg('User bot posting message to IRC')
        method(channel, utils.format_irc_message(
            message,
            IRCBot.users,
            IRCBot.channels,
        ))
