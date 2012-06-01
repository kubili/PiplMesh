import json, urllib, urlparse

from django.conf import settings
from django.core import urlresolvers
from django.utils import crypto

from mongoengine import queryset
from mongoengine.django import auth

import tweepy

from piplmesh.account import models

LAZYUSER_USERNAME_TEMPLATE = 'guest-%s'

class MongoEngineBackend(auth.MongoEngineBackend):
    # TODO: Implement object permission support
    supports_object_permissions = False
    # TODO: Implement anonymous user backend
    supports_anonymous_user = False
    # TODO: Implement inactive user backend
    supports_inactive_user = False

    def authenticate(self, username, password):
        user = self.user_class.objects(username__iexact=username).first()
        if user:
            if password and user.check_password(password):
                return user
        return None

    def get_user(self, user_id):
        try:
            return self.user_class.objects.with_id(user_id)
        except self.user_class.DoesNotExist:
            return None

    @property
    def user_class(self):
        return models.User

class FacebookBackend(MongoEngineBackend):
    """
    Facebook authentication.
    """

    def authenticate(self, facebook_token, request):
        """
        Retrieves an access token and Facebook data. Determine if user already
        exists. If not, a new user is created. Finally, the user's Facebook
        data is saved.
        """
    
        args = {
            'client_id': settings.FACEBOOK_APP_ID,
            'client_secret': settings.FACEBOOK_APP_SECRET,
            'redirect_uri': request.build_absolute_uri(urlresolvers.reverse('facebook_callback')),
            'code': facebook_token,
        }
    
        # Retrieve access token
        url = urllib.urlopen('https://graph.facebook.com/oauth/access_token?%s' % urllib.urlencode(args)).read()
        response = urlparse.parse_qs(url)
        access_token = response['access_token'][-1]
    
        # Retrieve user's public profile information
        data = urllib.urlopen('https://graph.facebook.com/me?%s' % urllib.urlencode({'access_token': access_token}))
        fb = json.load(data)

        # TODO: Check if id and other fields are returned
        # TODO: Move user retrieval/creation to User document/manager
        # TODO: get_or_create implementation has in fact a race condition, is this a problem?
        user, created = self.user_class.objects.get_or_create(
            facebook_id=fb.get('id'),
            defaults={
                'username': fb.get('username', fb.get('first_name') + fb.get('last_name')),
                'first_name': fb.get('first_name'),
                'last_name': fb.get('last_name'),
                'email': fb.get('email'),
                'gender': fb.get('gender'),
                'facebook_link': fb.get('link'),
            }
        )
        user.facebook_token = access_token
        user.save()

        return user

class TwitterBackend(MongoEngineBackend):
    """
    Twitter authentication.
    """

    def authenticate(self, twitter_token, request):
        twitter_auth = tweepy.OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET)
        twitter_auth.set_access_token(twitter_token.key, twitter_token.secret)
        api = tweepy.API(twitter_auth)
        twitter_user = api.me()
        user, created = self.user_class.objects.get_or_create(
            twitter_id = twitter_user.id,
            defaults = {
                'username': twitter_user.screen_name,
                'first_name': twitter_user.name,
            }
        )
        user.twitter_token_key = twitter_token.key
        user.twitter_token_secret = twitter_token.secret
        user.save()
        return user

class FoursquareBackend(MongoEngineBackend):
    """
    Foursquare authentication.
    """

    def authenticate(self, foursquare_token=None, request=None):
        args = {
            'client_id': settings.FOURSQUARE_CLIENT_ID,
            'client_secret': settings.FOURSQUARE_CLIENT_SECRET,
            'redirect_uri': request.build_absolute_uri(urlresolvers.reverse('foursquare_callback')),
            'code': foursquare_token,
            'grant_type': 'authorization_code',
        }

        # Retrieve access token
        url = urllib.urlopen('https://foursquare.com/oauth2/access_token?%s' % urllib.urlencode(args)).read()
        response = json.loads(url)
        access_token = response.get('access_token')

        # Retrieve user's public profile information
        data = urllib.urlopen('https://api.foursquare.com/v2/users/self?oauth_token=%s' % access_token)
        foursquare_data = json.load(data)
        foursquare_user = foursquare_data['response']['user']
        """
        Fields in foursquare_user:
        id - A unique identifier for this user.
        firstName - A user's first name.
        lastName - A user's last name.
        homeCity - User's home city.
        photo - URL of a profile picture for this user.
        gender - A user's gender: male, female, or none.
        relationship - (Optional) The relationship of the acting user (me) to this user (them).

        Present in user details:
        type, contact, pings, badges, checkins, mayorships, tips, todos, photos, friends, followers, 
        requests, pageInfo.
        """

        user, created = self.user_class.objects.get_or_create(
            foursquare_id=foursquare_user.get('id'),
            defaults={
                'username': foursquare_user.get('firstName', {}) + foursquare_user.get('lastName', {}),
                'first_name': foursquare_user.get('firstName', {}),
                'last_name': foursquare_user.get('lastName', {}),
                'email': foursquare_user.get('contact', {}).get('email'),
                'gender': foursquare_user.get('gender', {}),
                'foursquare_picture_url': foursquare_user.get('photo', {})
            }
        )
        user.foursquare_token = access_token
        user.save()
        return user

class LazyUserBackend(MongoEngineBackend):
    def authenticate(self):
        while True:
            try:
                username = LAZYUSER_USERNAME_TEMPLATE % crypto.get_random_string(6)
                user = self.user_class.objects.create(
                    username=username,
                )
                break
            except queryset.OperationError, e:
                msg = str(e)
                if 'E11000' in msg and 'duplicate key error' in msg and 'username' in msg:
                    continue
                raise

        return user
