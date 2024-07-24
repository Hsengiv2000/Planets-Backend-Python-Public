from tokenize import group
import pymongo
from bson.objectid import ObjectId
from pymongo import MongoClient
from stripe import Refund
from torch import group_norm
from admintools import stripetools
from models import UserModel
from pymongo import ReturnDocument
import copy 
from datetime import datetime
import time
from multiprocessing import Process
import random

#todo write init function to handle init
client = MongoClient()

usercol = client.userdb.usercol
chatscol = client.chatsdb.chatscol
threadscol = client.chatsdb.threadscol
userChatsCol = client.userChatdb.userchatscol
messagesCol = client.messagesDB.messagesCol
threadMessagesCol = client.messagesDB.threadMessagesCol
groupPaymentsCol = client.paymentsDB.groupPaymentsCol
userPaymentsCol = client.paymentsDB.userPaymentsCol
groupTimingsCol = client.groupTimingsDB.groupDeadlineCol
userKickoutTimingsCol = client.groupTimingsDB.userKickoutTimingsCol
userLeftCol = client.userChatdb.userLeftCol
groupPackagesCol = client.packagesdb.groupPackagesCol


scheduledGroupMemberProcessingCache = {}

def check_if_user(username, password):
    user = usercol.find_one({"username": username, "password":password}) 
    print("WE FOUND A BROTHER, ", user)
    return user

def check_if_email_and_user(username, email):
    print("CHECKING USER", usercol.find_one({"username": username, "email": email}))
    return usercol.find_one({"username": username, "email": email})

def check_if_email(email):
    print("CHECKING EMAIL", usercol.find_one({ "email": email}))
    return usercol.find_one({"email": email})


def create_user(username, password, email, customer):
    usercol.insert_one({"username": username, "email": email, "password": password, "has_confirmed": False, "stripe_customer_id": customer['id']})
    user = usercol.find_one({"username": username, "email": email})
    userChatsCol.insert_one({"user_id": str(user["_id"]), "groups": []})
    return user

def get_user(username, email):
    user = usercol.find_one({"username": username, "email": email}) 
    if user == None:
        return {"message": "User not found", "has_confirmed": False}
    else:
        if user["has_confirmed"] == False:
            return {"message": "Please confirm your account", "has_confirmed": False}
        user = UserModel.User(user["username"], user["password"], user["email"], str(user["_id"])).__dict__
        user["message"] = "Successfully confirmed"
        del user["password"]
        return user

def get_username_from_id(user_id):
    user = usercol.find_one({"_id": ObjectId(user_id)})
    if user == None:
        return None
    else:
        return user["username"]

def get_user_object_from_id(user_id):
    userObject = usercol.find_one({"_id": ObjectId(user_id)})
    
    del userObject["_id"]
    userObject["id"] = user_id
    return userObject

def confirm_user(email):
    filter = {"email": email}
    newvalues = {"$set":{"has_confirmed": True}}
    usercol.update_one(filter, newvalues)
    print("Confirmed user")

def update_user(user_id, update_body):
    updated_cursor =  usercol.find_one_and_update({"_id": ObjectId(user_id)}, {"$set": update_body },
                        return_document = ReturnDocument.AFTER)
    print(updated_cursor)
    del updated_cursor["_id"]
    updated_cursor["id"] = user_id
    return updated_cursor


# case joinDuringExpiry = 0,, joinDuringExpiryUntilKickout = 1, joinImmediatelyUntilKickout = 2, joinPermanent = 3, inviteOnly = 4

def register_chat_group(group_id, celeb_name, celeb_id, group_name, start_time, group_expiry, imageURL,entry_strategy,group_description, limit, packages):
    #todo authorname group name shenanigaans
    group_created_object = chatscol.insert_one({"celeb_name": celeb_name, "celeb_id": celeb_id ,"group_id": group_id, "members": [], "group_name": group_name, "start_time": start_time, "expiry_time": group_expiry, "image_url":imageURL, "entry_strategy":entry_strategy, "group_description": group_description, "limit": limit})
    if entry_strategy in [0,1] :
        groupTimingsCol.insert_one({"celeb_name": celeb_name, "celeb_id": celeb_id ,"group_id": group_id, "group_name": group_name,"start_date": datetime.fromtimestamp(start_time).replace(second=0, microsecond=0), "start_time": start_time, "entry_strategy":entry_strategy,  "limit": limit, "expiry_time": group_expiry, "expiry_date": datetime.fromtimestamp(group_expiry).replace(second=0, microsecond=0)})

    user = userChatsCol.find_one({"user_id": celeb_id})
    old_groups = None
    if user != None:
        old_groups = user["groups"]
    if old_groups == None:
        old_groups = []
    old_groups.append(group_id)
    print(old_groups)
    if user != None:
        userChatsCol.update_one({"user_id": celeb_id}, { "$set": { "groups": old_groups } })
    else:
        userChatsCol.insert_one({"user_id": celeb_id, "groups": old_groups } )
    for package in packages:
        print("GOING THROUGH PACKAGE", package)
        add_chat_package(group_id, celeb_id, package["amount"], package.get("kickout_time", None))

def register_chat_group_thread(group_id, message_id, celeb_id, message_sender_id):
    threadObject = threadscol.insert_one({"group_id": group_id, "message_id": message_id, "message_sender_id": message_sender_id, "celeb_id": celeb_id})
    print("THREAD OBJECT IS fdsffsd", {"group_id": group_id, "message_id": message_id, "user_id": message_sender_id, "celeb_id": celeb_id, "thread_id": threadObject.inserted_id}
    )
    message_object = messagesCol.update_one({"group_id": group_id, "_id": ObjectId(message_id)}, {"$set": {"thread" : create_thread_object(celeb_id, message_sender_id, group_id, message_id, str(threadObject.inserted_id))}})
    print("Raw result is ", message_object.raw_result)
    return {"group_id": group_id, "message_id": message_id, "user_id": message_sender_id, "celeb_id": celeb_id, "thread_id": str(threadObject.inserted_id)}
    

def create_thread_object(celeb_id, message_sender_id, group_id, message_id, thread_id):
    return {"thread_id": thread_id, "user_id": message_sender_id, "group_id": group_id, "celeb_id": celeb_id, "message_id": message_id}


def user_join_chat_group(group_id, user_id, kickout_time = None):
    group = chatscol.find_one({"group_id": group_id})
    old_members = group["members"]
    old_members.append(user_id)
    chatscol.update_one({"group_id": group_id}, { "$set": { "members": old_members } })
    user = userChatsCol.find_one({"user_id": user_id})
    old_groups = None
    if user != None:
        old_groups = user["groups"]
    if old_groups == None:
        old_groups = []
    if group_id not in old_groups:
        old_groups.append(group_id)
    print("entering join chat")
    print(old_groups)
    if kickout_time != None:
        kickout_time = int(kickout_time)
    if kickout_time != None:
        start_time = group.get("start_time", None)
        if start_time != None:
            kickout_time = start_time + (kickout_time * 60)
        else:
            kickout_time = kickout_time * 60
    if user != None:
        
        kickout_dic = user.get("kickout_time", {})
        
        if kickout_time != None:
            
            print("Joining Chat group with 1 ", group_id, user_id, kickout_time, kickout_dic)
            kickout_dic[group_id] = kickout_dic.get(group_id, 0) +  kickout_time 
            kickout_time = kickout_dic[group_id]
            userChatsCol.update_one({"user_id": user_id}, { "$set": { "groups": old_groups, "kickout_time": kickout_dic} })
        else:
            
            print("Joining Chat group with 2 ", group_id, user_id, kickout_time, kickout_dic)
            userChatsCol.update_one({"user_id": user_id}, { "$set": { "groups": old_groups } })
    else:
        if kickout_time == None:
            
            print("Joining Chat group with 3 ", group_id, user_id, kickout_time, kickout_dic)
            userChatsCol.insert_one({"user_id": user_id, "groups": old_groups } )
        else:
            
            print("Joining Chat group with 4 ", group_id, user_id, kickout_time, kickout_dic)
            userChatsCol.insert_one({"user_id": user_id, "groups": old_groups, "kickout_time": {group_id: kickout_time} } )


    userLeftCol.delete_one({"user_id": user_id, "group_id": group_id})
    if kickout_time!= None and group["entry_strategy"] in [1,2]:
        userKickoutTimingsCol.update_one({"user_id": user_id, "group_id": group_id},{"kickout_time": datetime.fromtimestamp(kickout_time).replace(second=0, microsecond=0)}, upsert = True)

def add_chat_package(groupid, userid, amount, kickout_time):
    groupPackagesCol.insert_one({"group_id": groupid, "user_id": userid, "amount": amount, "kickout_time": kickout_time})

def obtain_chat_packages(groupid):
    object = groupPackagesCol.find({"group_id": groupid})
    temp = []
    for package in object:
        package_id = str(package["_id"])
        del package["_id"]
        package["package_id"] = package_id
        temp.append(package)
    return temp

def user_leave_chat_group(group_id, user_id):
    group = chatscol.find_one({"group_id": group_id})
    
    old_members = group.get("members", None)
    if old_members == None:
        old_members = []
    else: 
        try:
            old_members.remove(user_id)
        except:
            print("cant remove old memebr i think error")
    chatscol.update_one({"group_id": group_id}, { "$set": { "members": old_members } })
    user = userChatsCol.find_one({"user_id": user_id})
    if user != None:
        
        old_groups = user.get("groups", [group_id])
        old_groups.remove(group_id)
        kickout_dic = user.get("kickout_time", None)
        if kickout_dic != None and group_id in kickout_dic:
            del kickout_dic[group_id]

        userChatsCol.update_one({"user_id": user_id}, { "$set": { "groups": old_groups, "kickout_time": kickout_dic } })
    else:
        userChatsCol.insert_one({"user_id": user_id, "groups": [] } )

    userLeftCol.insert_one({"group_id": group_id,"user_id": user_id})
        
def get_group_object_by_id(groupID):
    groupObject = chatscol.find_one({"group_id": groupID})
    del groupObject["_id"]
    return groupObject

def get_random_chats():
    return chatscol.find().limit(40)

def get_user_paid_and_joined_chats(userID):
    
    groups = get_user_chats(userID) #all joined groups
    paid_chats = obtain_user_group_purchases(userID)
    new_list = copy.deepcopy(groups) + copy.deepcopy(list(paid_chats.keys()))
    return new_list

def get_user_chats_objects(userID):
    groups = get_user_chats(userID) #all joined groups
    paid_chats = obtain_user_group_purchases(userID)
    new_list = copy.deepcopy(groups) + copy.deepcopy(list(paid_chats.keys()))
    new_list = set(new_list)
    groupObjects = []
    for i in new_list:
        groupObject = get_group_object_by_id(i)
        if i in groups:
            groupObject["join_paid_status"] = 2
        else:
            groupObject["join_paid_status"] = 1
        groupObjects.append(groupObject)
    
    return {"groups": groupObjects}


def get_user_chats(userID):
    groups = userChatsCol.find_one({"user_id": userID})
    print("#Q$#$$#@#$@#$@$#")
    print(groups)
    print("#@$@#$@#$#@$@#$")
    if groups ==None or groups["groups"]  == None:
        return []
    return groups["groups"] 

def fetch_messages(user_id, group_id, cursor):
    messages = []
    cursor = int(cursor)
    messages_object = messagesCol.find({"group_id": group_id}).sort([( '$natural', -1 )] ).skip(cursor).limit(20)
    for i in messages_object:
        print(i)
        temp = i 
        temp["message_id"] = str(temp["_id"])

        del temp["_id"]
        messages.append(temp)
    print("THE MESSAGES AREEEE", messages)
    return messages

def fetch_thread_messages(user_id, group_id, thread_id, cursor):
    messages = []
    cursor = int(cursor)
    messages_object = threadMessagesCol.find({"group_id": group_id, "thread_id": thread_id}).sort([( '$natural', -1 )] ).skip(cursor).limit(20)
    for i in messages_object:
        print(i)
        temp = i 
        temp["message_id"] = str(temp["_id"])
        del temp["_id"]
        messages.append(temp)
    print("THE THREAD MESSAGES AREEEE", messages)
    return messages
 

def fetch_group_members(groupid):
    members = chatscol.find_one({"group_id": groupid})["members"]
    groupMembers = []
    for i in members:
        groupMembers.append(get_user_object_from_id(i))
    return {"users": groupMembers}

def make_payment_confirmation(customerid, productid, userid, amount, currency, invoiceid, paymentintentid, createdat, kickout_time):
    if userid == None:
        userid = str(usercol.find_one({"stripe_customer_id": customerid})["_id"])
    if kickout_time != None:
        kickout_time = int(kickout_time)
    groupPaymentsCol.insert_one({"stripe_customer_id": customerid, "group_id": productid, "user_id": userid, "amount": amount, "currency": currency, "stripe_invoice_id": invoiceid, "stripe_payment_intent_id": paymentintentid, "created_at": createdat })
    userPaymentsObject = userPaymentsCol.find_one({"user_id": userid})
    new_amount = amount
    if userPaymentsObject != None:
        if productid in userPaymentsObject:
            new_amount += userPaymentsObject[productid]["amount"]
    userPaymentsCol.update_one({"user_id": userid}, {"$set": {productid: {"amount": new_amount, "refunded": False}}}, upsert=True)
    group = chatscol.find_one({"group_id": productid})
    if group == None:
        return 
    print("BROTHER WE ARRIVE YO")
    if group.get("start_time", None) == None or group["start_time"] < time.time() :

        print('cutie cutie')
        user_join_chat_group(productid, userid, kickout_time)
        print("wassup wassup")
    else:
        print('haiyoo da')
        obtainScheduleGroupProcessingActionDBConnection(productid).insert_one({"group_id": productid, "user_id": userid, "amount": amount, "currency": currency, "stripe_payment_intent_id":paymentintentid, "kickout_time": kickout_time })    
    return

    
#list of all purchases by the user
def obtain_user_purchases(userid):
    payments = groupPaymentsCol.find({"user_id": userid})
    payments_list = []
    for payment in payments:
        print(payment)
        del payment["_id"]
        payments_list.append(payment)
    return payments_list

#list of all purchases but aggregated by group
def obtain_user_group_purchases(userid):
    payments = userPaymentsCol.find_one({"user_id": userid})
    if payments == None:
        return {}
    del payments["_id"]
    del payments["user_id"]
    group_objects = userLeftCol.find({"user_id": userid})
    for object in group_objects:
        if object["group_id"] in payments:
            del payments[object["group_id"]]
    return payments

def scheduledUserKickoutProcessing():
    timestamp = time.time()
    date = datetime.fromtimestamp(timestamp).replace(second=0, microsecond=0)

    print("WE ARE AT THE SCHEDULED KICKOUT PROCESS", timestamp, date)
    usersToProcess = userKickoutTimingsCol.find({"kickout_time": date})
    #todo optimization
    for user in usersToProcess:
        userid = user["user_id"]
        groupid = user["group_id"]
        print("removing user from group ", userid, groupid)
        user_leave_chat_group(groupid, userid)

def scheduledGroupMemberProcessing():
    timestamp = time.time()
    date = datetime.fromtimestamp(timestamp).replace(second=0, microsecond=0)

    print("WE ARE AT THE SCHEDULED GROUP RECONSITALITON PROCESS", timestamp, date)
    start_groups_to_process = groupTimingsCol.find({"start_date": date})
    #todo optimization
    for group in start_groups_to_process:
        id = group["_id"]
        group_id = group["group_id"]
        entry_strategy = group["entry_strategy"]
        limit = group["limit"]
        proc = Process(target = randomUsersJoinAndRefund, args = (id, group_id, limit, entry_strategy, ))
        proc.start()
        
#TODO MAKE BULK BATCH MOGNO
def randomUsersJoinAndRefund(id,group_id, limit, entry_strategy):
    connection = obtainScheduleGroupProcessingActionDBConnection(group_id)
    users = connection.find({"group_id": group_id})
    userDict = {}
    for user in users:
        userid = user["user_id"]
        if userid in userDict:
            userDict[userid].append( (user["amount"], user["currency"] , user["stripe_payment_intent_id"], user["kickout_time"]) )
        else:
            userDict[userid] = [(user["amount"], user["currency"] , user["stripe_payment_intent_id"], user["kickout_time"])]
    if len(userDict) <= limit:
        for userid in userDict:
            combined_kickout_time = 0
            for payment in userDict[userid]:
                if payment[3] == None:
                    combined_kickout_time = None
                    break
                combined_kickout_time += payment[3]
            user_join_chat_group(group_id, userid, combined_kickout_time)
        groupTimingsCol.delete_one({"_id": id})

    else:
        joining_set = dict(random.sample(userDict.items(), limit))
        for userid in joining_set:
            
            combined_kickout_time = 0
            for payments in joining_set[userid]:
                if payments[3] == None:
                    combined_kickout_time = None
                    break
                combined_kickout_time += payment[3]
            user_join_chat_group(group_id, userid, combined_kickout_time)
            del userDict[userid]
        for userid in userDict:
            for payment in userDict[userid]:
                perform_refund_operation(userid, payment[2])
        groupTimingsCol.delete_one({"_id": id})

def obtainScheduleGroupProcessingActionDBConnection(group_id):
    if group_id in scheduledGroupMemberProcessingCache:
        return scheduledGroupMemberProcessingCache[group_id]
    else:
        temp = client.scheduledActionsDB[group_id]
        scheduledGroupMemberProcessingCache[group_id] = temp
        return temp

def perform_refund_operation(userid, stripe_payment_intent_id):
    stripetools.handle_refund(stripe_payment_intent_id) 
    
def update_refund(payment_intent, amount):
    payment_object = groupPaymentsCol.find_one({"stripe_payment_intent_id":payment_intent})
    if payment_object != None:
        user_id = payment_object["user_id"]
        user_payments_object = userPaymentsCol.find_one({"user_id": user_id})
        userPaymentsCol.update_one({"user_id": user_id}, {"$set": {payment_object["group_id"]: {"amount": user_payments_object["amount"], "refunded": True}}}, upsert=True)
        refunded = payment_object.get("refunded", 0) + amount
        groupPaymentsCol.update_one({"group_id":payment_object["group_id"]}, {"$set": {"refunded":refunded}}, upsert=True)