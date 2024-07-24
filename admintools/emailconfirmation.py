from itsdangerous import URLSafeTimedSerializer
import app

def generate_confiramtion_token(email):
    serializer = URLSafeTimedSerializer("secretkey")
    return serializer.dumps(email, salt = "salt")

def confirm_token(token, expiration = 3600):
    serializer = URLSafeTimedSerializer("secretkey")
    try:
        email = serializer.loads(token, salt = "salt", max_age = expiration)
    except Exception as e:
        print("THE SERIALIZER ERROR IS", e)
        return False
    return email