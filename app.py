from flask import Flask, session, url_for, jsonify
import os
from mongoutils import mongoutil
from flask import request, Response
from admintools import emailconfirmation, mailsender, stripetools, google_utils
import hashlib
from config import BaseConfig
from flask_mail import Mail, Message
import json
import time
import threading

print("STARTING FLASK")

#  $ export FLASK_APP=hello.py
#export FLASK_ENV=development
# $ python3 -m flask run --host=0.0.0.0
  
app = Flask(__name__)
mail= Mail(app)

def login_required(func):
    def check_login(*args, **kwargs):
        print("session", session)
        if "userid" not in session :
            return "Requies login"
        return func(*args, **kwargs)
    check_login.__name__ = func.__name__ #this is done because to avoid "  View function mapping is overwriting an existing endpoint function: check_login " as we use the wrapper on multiple routes
    return check_login 


@app.route("/", methods = ["GET"])
@login_required
def hello_world():
    
    hostname = request.headers.get('Host')
    print(hostname)
    link = stripetools.create_payment_link(STRIPE_PROD_URL, "usd")
    print("THE STUFF ARE", link["id"], link["url"])
    return link["url"]
    
@app.route("/user/<userid>/chats/<groupid>/<cursor>", methods = ["GET"])
@login_required
def fetch_messages_for_chat(userid, groupid, cursor):
    messages = {"messages": mongoutil.fetch_messages(userid, groupid, cursor)}
    response = app.response_class(
        response=json.dumps(messages),
        status=200,
        mimetype='application/json'
    )
    return response

def create_response_object(resp):
    response = app.response_class(
        response=json.dumps(resp),
        status=200,
        mimetype='application/json'
    )
    return response

@app.route("/user/<userid>/chats/<groupid>/thread/<threadid>/<cursor>", methods = ["GET"])
@login_required
def fetch_thread_messages_for_chat(userid, groupid, threadid, cursor):
    messages = {"messages": mongoutil.fetch_thread_messages(userid, groupid, threadid, cursor)}
    response = app.response_class(
        response=json.dumps(messages),
        status=200,
        mimetype='application/json'
    )
    return response

@app.route("/login", methods = ["POST"])
def login():
    body = request.json
    username = body["username"]
    password = body["password"]
    hashed_password = hashlib.md5(password.encode()).hexdigest()
    print("username is", username)
    print("password is", hashed_password)
    user = mongoutil.check_if_user(username, hashed_password)
    print('before', user)
    if user != None:
        session["userid"] = True
        user["id"] = str(user["_id"])
        del user["_id"]
        del user["password"]
        print(user)
        return user, 200
    else:
        
        return Response("{}}", status=401)
    
@app.route("/logout", methods = ["POST"])
@login_required
def logout():
    session["userid"] = False
    del session["userid"]
    return Response("{}", status = 200)

@app.route("/signup", methods=["POST"])
def signup():
    print(request)
    try:
        body = request.json
    except Exception as e:
        print(e)
        return "supp"
        
    username = body["username"]
    password = body["password"]
    email = body["email"]
    hashed_password = hashlib.md5(password.encode()).hexdigest()
#todo handle email checks
    if mongoutil.check_if_email_and_user(username, email) == None:
        token = emailconfirmation.generate_confiramtion_token(email)

        confirm_url = url_for('confirm_email', token=token, _external=True)
        mailsender.send_email(app,email, username, confirm_url)
        customer = stripetools.create_customer()

        user = mongoutil.create_user(username, hashed_password, email, customer )
        stripetools.update_customer_user_cache(customer["id"], user["_id"])
        return Response("{}", status = 200)
    return Response("{}", status = 401)

@app.route("/confirm/<token>",methods=["GET"])
def confirm_email(token):
    try:
        print("CONFIRMATION TOKEN IS", token)
        email = emailconfirmation.confirm_token(token)
    except Exception as e:
        print("Failed confirming email", e)
        return Response("{}", status = 400)

    if mongoutil.check_if_email(email) != None:
        mongoutil.confirm_user(email)
    else:
        return Response("{}", status = 401)
    return Response("EMAIL SUCCESSFULLY CONFIRMED!", status = 200)

@app.route("/user/<userid>/update", methods = ["POST"])
@login_required 
def update_user(userid):
    print(request.json)
    #todo unique user
    updated_user_object = mongoutil.update_user(userid, request.json)
    return create_response_object(updated_user_object)

@app.route('/webhookreceiver', methods=['POST'])
def webhookreceiver():
    return stripetools.handle_webhook(request.json)


# ANYTHING THAT REQUIRES STRIPE
# case joinDuringExpiry = 0,, joinDuringExpiryUntilKickout = 1, joinImmediatelyUntilKickout = 2, joinPermanent = 3, inviteOnly = 4
# case joinDuringGroupStartTime = 0
#     case joinDuringGroupStartTimeUntilKickout
#     case joinImmediatelyUntilKickout
#     case joinPermanent
#     case inviteOnly = 4

@app.route("/chat/create", methods = ["POST"])
@login_required
def create_celeb_chat():
    if request.method == 'POST': 
        userid = request.json["user_id"]
        group_name = request.json["group_name"]
        start_time = request.json.get("start_time", None)
        imageURL = request.json.get("thumbnail_url", "")
        entry_strategy = request.json["entry_strategy"]
        group_expiry = request.json["expiry_time"]
        group_description = request.json.get("group_description","Placeholder description")
        limit = request.json.get("limit", 200)
        packages = request.json["packages"]
        created_product_object = stripetools.create_groupchat_as_product("CELEBCHAT:"+userid)
        user_name = mongoutil.get_username_from_id(userid)
        if user_name == None:
            return Response("{}", status = 400)
        mongoutil.register_chat_group(created_product_object.id, user_name, userid, group_name, start_time, group_expiry, imageURL, entry_strategy,group_description, limit, packages)
        return Response("{}", status=200)
    return Response("{}", status = 500)

@app.route("/chat/thread/create", methods = ["POST"])
@login_required 
def create_celeb_chat_thread():
     if request.method == 'POST':
        celeb_id = request.json["celeb_id"]
        message_sender_id = request.json["sender_id"]
        group_id = request.json["group_id"]
        message_id = request.json["message_id"]
        threadObject = mongoutil.register_chat_group_thread(group_id, message_id, celeb_id, message_sender_id)
        print("threadobject is", threadObject)
        response = app.response_class(
        response=json.dumps(threadObject),
        status=200,
        mimetype='application/json'
        )
        return response
     return Response("{}", status = 500)


@app.route("/mockcelebchat/<groupid>/<groupname>", methods = ["GET"])
def mockcelebchat(groupid, groupname):
    mongoutil.register_chat_group(groupid, groupname)
    return "succ"

@app.route("/user/<userid>/chat/pay", methods = ["POST"])
@login_required
def pay_for_chat(userid):
    if request.method == "POST":
        body = request.json
        groupid = body["group_id"]
        amount = body["amount"]
        kickout_time = body.get("kickout_time", None)
        customer = mongoutil.get_user_object_from_id(userid)
        email = customer["email"]
        customerid = customer.get("stripe_customer_id", None)
        if customerid == None:
            customerid = stripetools.create_customer()["id"]
            mongoutil.update_user(userid, {"stripe_customer_id": customerid})
        stripetools.update_customer_user_cache(customerid, userid)
                
        responseObject = stripetools.create_payment_intent_object(groupid, email,customerid, "sgd" , amount * 100, kickout_time)
        
        return responseObject
    return Response("{}", status = 500)
   
  #for all payments 
@app.route("/user/<userid>/obtain-payments", methods=["GET"])
@login_required
def obtain_user_purchases(userid):
    return create_response_object({"purchases": mongoutil.obtain_user_purchases(userid)})

#for sum of group payments
@app.route("/user/<userid>/obtain-group-payments", methods=["GET"])
@login_required
def obtain_user_group_purchases(userid):
    return create_response_object({"groups": mongoutil.obtain_user_group_purchases(userid)})

@app.route("/user/<userid>/chat/join", methods = ["POST"])
@login_required
def join_celeb_chat(userid):
    if request.method == "POST": 
        body = request.json
        groupid = body["group_id"]
        kickout_time = body.get("kickout_time", None)
        mongoutil.user_join_chat_group(groupid, userid, kickout_time)
        print("WE ARE HERE")
    return Response("{}", status = 200)

@app.route("/user/<userid>/chat/packages", methods = ["POST"])
@login_required
def chat_add_package(userid):
    if request.method == "POST": 
        body = request.json
        groupid = body["group_id"]
        amount = body.get("amount", 0)
        kickout_time = body.get("kickout_time", None)
        mongoutil.add_chat_package(groupid, userid, amount, kickout_time)
        print("WE ARE HERE")
    return Response("{}", status = 200) 

@app.route("/chat/packages/<groupid>", methods = ["GET"])
@login_required
def chat_get_packages(groupid):
    if request.method == "GET": 
        return create_response_object({"packages": mongoutil.obtain_chat_packages(groupid)})
        print("WE ARE HERE")
    return Response("{}", status = 400) 

@app.route("/user/<userid>/chat/leave", methods = ["POST"])
@login_required
def leave_celeb_chat(userid):
    if request.method == "POST": 
        body = request.json                              
        groupid = body["group_id"]
        mongoutil.user_leave_chat_group(groupid, userid)
        print("WE ARE HERE")
    return Response("{}", status = 200)

@login_required
@app.route("/chat/<groupid>/members", methods=["GET"])
def get_group_members(groupid):
    return create_response_object(mongoutil.fetch_group_members(groupid))


@login_required
@app.route("/recommendedChats/<userID>", methods=["GET"])
def recommendedChatsForUser(userID):
    #get random chats
    #get user chats
    random_chats  = mongoutil.get_random_chats()
    user_chats = mongoutil.get_user_paid_and_joined_chats(userID)
    print("USER CHATS ARE ", user_chats)
    print("RANDOM CHATS ARE,", random_chats)
    final_chat_list = []

    for group in random_chats:
        new_group = group
        del new_group["_id"]
        
        if group["group_id"] in user_chats or group["celeb_id"] == userID:
            continue  
        else:
            new_group["join_paid_status"] = 0

            final_chat_list.append(new_group)
    print(final_chat_list)
    final_response = {"groups": final_chat_list}
    print(final_response)
    response = app.response_class(
        response=json.dumps(final_response),
        status=200,
        mimetype='application/json'
    )
    return response

@login_required
@app.route("/user/<userid>/chats", methods=["GET"])
def get_user_chats(userid):
    return create_response_object(mongoutil.get_user_chats_objects(userid))

@login_required
@app.route("/firebaseauth", methods = ["POST"])
def firebaseauth():
    if request.method == "POST":
        uid = request.json["userid"]
        authObject = google_utils.create_token_uid(uid)
        response = app.response_class(
            response=json.dumps({"auth_token": authObject.decode('UTF-8')}),
            status=200,
            mimetype='application/json'
        )
        return response

    return 400



#TODO
@app.route("/deactivatepaymentlink/<paymentlink>")
def deactivate_payment_link(paymentlink):
    stripetools.deactivate_payment_link(paymentlink)
 
def startBackgroundTasks():
    thread = threading.Thread(target=performScheduledGroupMemberProcessing)
    thread.start()
    print("Started backgroun thread")

def performScheduledGroupMemberProcessing():
    while 1:
        thread = threading.Thread(target=mongoutil.scheduledGroupMemberProcessing)
        thread.start()
        thread2 = threading.Thread(target = mongoutil.scheduledUserKickoutProcessing)
        thread2.start()
        time.sleep(59.9)

if __name__ == '__main__':
    startBackgroundTasks()
    app.run(host="0.0.0.0", port=5000)
    print("started app already")