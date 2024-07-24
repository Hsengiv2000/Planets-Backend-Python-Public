import app
from flask_mail import Mail, Message

def send_email(application, email, username, token):
    msg = Message('Hello', sender = 'testfellagoat@gmail.com', recipients = [email])
    msg.body = "Hi " + username.strip().split()[0] +", Welcome to planets!, please confirm your email address by opening this link! " + token
    Mail(application).send(msg)