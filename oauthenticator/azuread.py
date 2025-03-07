"""
Custom Authenticator to use Azure AD with JupyterHub
"""

import json
import os
import urllib
from distutils.version import LooseVersion as V

import jwt
from jupyterhub.auth import LocalAuthenticator
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from traitlets import Unicode, default

from .oauth2 import OAuthenticator


# pyjwt 2.0 has changed its signature,
# but mwoauth pins to pyjwt 1.x
PYJWT_2 = V(jwt.__version__) >= V("2.0")


class AzureAdOAuthenticator(OAuthenticator):
    login_service = Unicode(
        os.environ.get('LOGIN_SERVICE', 'Azure AD'),
        config=True,
        help="""Azure AD domain name string, e.g. My College"""
    )

    tenant_id = Unicode(config=True, help="The Azure Active Directory Tenant ID")

    access_token_version = 1

    @default('tenant_id')
    def _tenant_id_default(self):
        return os.environ.get('AAD_TENANT_ID', '')

    username_claim = Unicode(config=True)

    @default('username_claim')
    def _username_claim_default(self):
        return 'name'

    @default("authorize_url")
    def _authorize_url_default(self):
        if self.access_token_version == 1:
            return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/authorize"
        elif self.access_token_version == 2:
            return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
        else:
            raise ValueError('Invalid token version!')

    @default("token_url")
    def _token_url_default(self):
        if self.access_token_version == 1:
            return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/token"
        elif self.access_token_version == 2:
            return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        else:
            raise ValueError('Invalid token version!')

    async def get_user_attributes(self, oid):
        http_client = AsyncHTTPClient()

        params = dict(
            scope=["https://graph.microsoft.com/.default"],
            client_secret=self.client_secret,
            grant_type="client_credentials",
            client_id=self.client_id,
        )
        data = urllib.parse.urlencode(
            params, doseq=True, encoding='utf-8', safe='='
        )
        headers = {
            'Content-Type':
            'application/x-www-form-urlencoded; charset=UTF-8'
        }
        req = HTTPRequest(
            self.token_url,
            method="POST",
            headers=headers,
            body=data
        )
        resp = await http_client.fetch(req)
        resp_json = json.loads(resp.body.decode('utf8', 'replace'))
        access_token = resp_json["access_token"]

        headers = {
            'Authorization':
            'Bearer {0}'.format(access_token)
        }
        req = HTTPRequest(
            f"https://graph.microsoft.com/v1.0/users/{oid}",
            method="GET",
            headers=headers,
        )
        resp = await http_client.fetch(req)
        resp_json = json.loads(resp.body.decode('utf8', 'replace'))
        return resp_json


    async def authenticate(self, handler, data=None):
        code = handler.get_argument("code")

        params = dict(
            client_id=self.client_id,
            client_secret=self.client_secret,
            grant_type='authorization_code',
            code=code,
            redirect_uri=self.get_callback_url(handler))

        data = urllib.parse.urlencode(
            params, doseq=True, encoding='utf-8', safe='=')

        url = self.token_url

        headers = {
            'Content-Type':
            'application/x-www-form-urlencoded; charset=UTF-8'
        }
        req = HTTPRequest(
            url,
            method="POST",
            headers=headers,
            body=data  # Body is required for a POST...
        )

        resp_json = await self.fetch(req)

        access_token = resp_json['access_token']
        id_token = resp_json['id_token']

        if PYJWT_2:
            decoded = jwt.decode(
                id_token,
                options={"verify_signature": False},
                audience=self.client_id,
            )
        else:
            # pyjwt 1.x
            decoded = jwt.decode(id_token, verify=False)

        self.log.warning(repr(decoded))
        userdict = {"name": decoded[self.username_claim]}
        userdict["auth_state"] = auth_state = {}
        auth_state['access_token'] = access_token
        # results in a decoded JWT for the user data
        auth_state['user'] = decoded

        return userdict


class LocalAzureAdOAuthenticator(LocalAuthenticator, AzureAdOAuthenticator):
    """A version that mixes in local system user creation"""
    pass
