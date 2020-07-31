slackbridge
===========

[![Build Status](https://jenkins.ocf.berkeley.edu/buildStatus/icon?job=ocf/slackbridge/master)](https://jenkins.ocf.berkeley.edu/job/ocf/job/slackbridgejob/master/) [![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)

A OCF bridge between OCF IRC and Slack

Inspired by [slack-irc](https://github.com/ekmartin/slack-irc), which is an
awesome project to bridge between IRC and Slack. We wanted a more customized
version of that project that allowed for a bot per Slack user and mirrored
channels. We also like using Python for things instead of Node.js, so this
project was born out of those motivations.

## Developing

To run this bot in development, run the command below. This is best run on
supernova, since it already has the right config files to develop with:

    make dev

The first time you run this it will be slow as it installs dependencies, but in
subsequent runs, it will be much faster. If you want to manually specify the
config, run:

    make venv
    venv/bin/python -m slackbridge.main -c /path/to/slackbridge.conf

instead, but if you are developing on supernova, you should not have to do this.
`slackbridge.conf` contains the Slack API token, IRC NickServ password, etc. so
it is meant to be kept secret, but there is a sample config file provided at
`slackbridge.conf.sample` to show the structure of the file.
