#!/usr/bin/env python3
"""Bridge between IRC and Slack"""
import argparse
import ssl
import threading
import time
from configparser import ConfigParser
from datetime import date

import irc.bot
import irc.connection

IRC_HOST = 'dev-irc.ocf.berkeley.edu'
IRC_PORT = 6697

IRC_CHANNELS = ('#test',)

IRC_NICKNAME = 'slack-bridge-test'


class CreateBot(irc.bot.SingleServerIRCBot):

    def __init__(self, nickserv_password):
        self.topics = {}
        self.nickserv_password = nickserv_password
        factory = irc.connection.Factory(wrapper=ssl.wrap_socket)

        super().__init__(
            [(IRC_HOST, IRC_PORT)],
            IRC_NICKNAME,
            IRC_NICKNAME,
            connect_factory=factory
        )

    def on_welcome(self, conn, _):
        conn.privmsg('NickServ', 'identify {}'.format(self.nickserv_password))

        for channel in IRC_CHANNELS:
            conn.join(channel)

    def on_pubmsg(self, conn, event):
        conn.privmsg(event.target, 'test message')


def bot_announce(bot, targets, message):
    for target in targets:
        bot.connection.privmsg(target, message)


def timer(bot):
    last_date = None
    while True:
        last_date, old = date.today(), last_date
        if old and last_date != old:
            bot.bump_topic()
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(
        description='OCF IRC to Slack bridge',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '-c',
        '--config',
        default='/opt/slackbridge/bridge.conf',
        help='Config file to read from.',
    )
    args = parser.parse_args()

    conf = ConfigParser()
    conf.read(args.config)

    # irc bot thread
    bot = CreateBot('tmp_passwd')
    bot_thread = threading.Thread(target=bot.start, daemon=True)
    bot_thread.start()

    # celery thread
    # celery_thread = threading.Thread(
    #    target=celery_listener,
    #    args=(bot, conf.get('celery', 'broker')),
    #    daemon=True,
    # )
    # celery_thread.start()

    # timer thread
    timer_thread = threading.Thread(
        target=timer,
        args=(bot,),
        daemon=True,
    )
    timer_thread.start()

    while True:
        for thread in (bot_thread, timer_thread):
            if not thread.is_alive():
                raise RuntimeError('Thread exited: {}'.format(thread))

        time.sleep(0.1)


if __name__ == '__main__':
    main()
