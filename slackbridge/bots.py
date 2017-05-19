from twisted.python import log
from twisted.words.protocols import irc

import slackbridge.utils as utils

IRC_NICKNAME = 'slack-bridge'


class BridgeBot(irc.IRCClient):
    nickname = IRC_NICKNAME

    def __init__(self, slack_client, nickserv_password, slack_uid, channels):
        self.topics = {}
        self.sc = slack_client
        self.nickserv_password = nickserv_password
        self.slack_uid = slack_uid
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
        self.sc.api_call(
            'chat.postMessage',
            channel=channel,
            text=message,
            as_user=False,
            username=user,
            icon_url=utils.user_to_gravatar(user),
        )

    def check_slack_rtm(self):
        message = self.sc.rtm_read()

        if message:
            log.msg(message)


class UserBot(irc.IRCClient):
    # Not implemented yet, but this will be so that there is a bot per Slack
    # user, like with the current bridge
    pass
