import hashlib

GRAVATAR_URL = 'http://www.gravatar.com/avatar/{}?s=48&r=any&default=identicon'


def user_to_gravatar(user):
    email_hash = hashlib.md5()
    email = '{}@ocf.berkeley.edu'.format(user)
    email_hash.update(email.encode())
    return GRAVATAR_URL.format(email_hash.hexdigest())
