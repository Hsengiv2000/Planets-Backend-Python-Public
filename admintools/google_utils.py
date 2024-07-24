from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
import firebase_admin
from firebase_admin import credentials
from firebase_admin import auth
from firebase_admin import exceptions
from firebase_admin import tenant_mgt


def create_token_uid(uid):
    cred = credentials.Certificate(GOOGLE_CERTIFICATE_URL)
    default_app = firebase_admin.initialize_app(cred)   
    # [START create_token_uid]
  
  
    custom_token = auth.create_custom_token(uid)
    # [END create_token_uid]
    #delete this and try if thigns fail
    firebase_admin.delete_app(default_app)
    return custom_token 