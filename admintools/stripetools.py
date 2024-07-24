import stripe
import flask
from flask import request, Response, jsonify
from flask import url_for
import app
import json

from mongoutils import mongoutil
stripe.api_key = STRIPE_API_KEY

customer_user_map = {}
user_customer_map = {}

def create_customer():
    customer = stripe.Customer.create()
    return customer

def update_customer_user_cache(userid, customerid):
    customer_user_map[customerid] = userid
    user_customer_map[userid] = customerid

def obtain_price_object(groupid, currency, amount):
    product_object = obtain_groupchat_product(groupid)
    price_object = stripe.Price.create( 
        currency=currency,
        unit_amount = amount,
        product=product_object["id"],
    ) 
    return price_object


def obtain_groupchat_product(groupid):
    product_object = stripe.Product.retrieve(groupid)
    return product_object

def create_groupchat_as_product(celeb_name):
    response = stripe.Product.create(name=celeb_name)
    return response

def create_invoice_item(customerid, priceid, invoice):
    invoice_item = stripe.InvoiceItem.create( customer=customerid, price=priceid, invoice = invoice["id"])
    return invoice_item

def create_invoice(customerid):
    invoice = stripe.Invoice.create(customer=customerid)
    return invoice

def create_payment_intent_object(groupid, email, customerid,currency, amount, kickout_time):
    print("CUSTOMER ID IS ", customerid)
    ephemeralKey = stripe.EphemeralKey.create(  customer=customerid, stripe_version='2022-11-15')
    price_object = obtain_price_object(groupid, currency, amount)
    
    invoice = create_invoice(customerid)
    
    invoice_item = create_invoice_item(customerid, price_object["id"], invoice)
    finalize_invoice = stripe.Invoice.finalize_invoice(invoice["id"],)
    print("the finalize invoice lines are", finalize_invoice)
    payment_intent_id = finalize_invoice["payment_intent"]
    print("payment INTENT ID IS", payment_intent_id)
    stripe.PaymentIntent.modify(payment_intent_id,  metadata={"kickout_time": kickout_time, "group_id": groupid},) 
    paymentIntent = stripe.PaymentIntent.retrieve(payment_intent_id,)
    return jsonify(paymentIntent=paymentIntent["client_secret"],
                 ephemeralKey=ephemeralKey["secret"],
                 customer=customerid,
                 publishableKey='pk_test_51LtXuqJA80nHDf86xUiFA4GkmSSVMKazasFBv3XeDPqVwC3ncCkH2vmxp6P5rf9W34yi1qi7N8oRxMEuULGv7mOY00tesBzb2b')

def create_payment_link(groupid, currency):
    price_object = stripe.Price.create(
        currency=currency,
        custom_unit_amount={"enabled": True},
        product=groupid,
    )   
    priceid = price_object["id"]
    payment_link = stripe.PaymentLink.create(
        line_items=[{"price": priceid, "quantity": 1}]
    )

    print("THEY PAYMENT LINK URL IS", url_for("deactivate_payment_link", paymentlink = payment_link["id"], _external = True))

    # stripe.PaymentLink.modify(
    #     payment_link,
    #     after_completion={"type": "redirect", "redirect": {"url": str(url_for("deactivate_payment_link", paymentlink=payment_link["id"], _external = True))}}
    # )
    return payment_link
    #prod_McnyMpZNbJ6k2c

def deactivate_payment_link(payment_link):
    print("deativating payment_link:" , payment_link)
    stripe.PaymentLink.modify(
        payment_link,
        active=False,
    )

def handle_refund(payment_intent_id):
    
    stripe.Refund.create(payment_intent=payment_intent_id)

def handle_webhook(payload):

    event = None

    try:
        event = stripe.Event.construct_from(
        payload, stripe.api_key
        )
    except ValueError as e:
        # Invalid payload
        return Response("{}", status = 500)
#hadnle invoice.finalized
  # Handle the event
    print("EVENT.type iss" , event.type)

    if event.type == "payment_intent.succeeded":
        print("sucecss machan")
        payment_intent_succeeded_object = event.data.object # contains a stripe.PaymentIntent
        print('PaymentIntent was successful!')
        # email = payment_intent["charges"]["data"][0]["billing_details"]["email"]
        # amount = payment_intent["amount"]
        # print(payment_intent["charges"])
        # print("Sandwish")
        customerid = payment_intent_succeeded_object["customer"]
        
        amount = payment_intent_succeeded_object["amount_received"]
        currency = payment_intent_succeeded_object["charges"]["data"][0]["currency"]
        metadata = payment_intent_succeeded_object["metadata"]
        productid = metadata["group_id"]
        kickout_time = metadata["kickout_time"]
        invoiceid = payment_intent_succeeded_object["charges"]["data"][0]["invoice"]
        paymentintentid = payment_intent_succeeded_object["id"]
        createdat = event.created

        print("CUSTOMER< PRODUCT ID, AMOUNT, CURRENCY IS" , customerid, productid, amount, currency)
        mongoutil.make_payment_confirmation(customerid, productid, customer_user_map.get(customerid, None), amount, currency, invoiceid, paymentintentid, createdat, metadata.get("kickout_time", None))
    

    # if event.type == 'invoice.payment_succeeded':
    #     invoice_succeeded_object = event.data.object # contains a stripe.PaymentIntent
    #     print('PaymentIntent was successful!')
    #     # email = payment_intent["charges"]["data"][0]["billing_details"]["email"]
    #     # amount = payment_intent["amount"]
    #     # print(payment_intent["charges"])
    #     # print("Sandwish")
    #     customerid = invoice_succeeded_object["customer"]
    #     productid = invoice_succeeded_object["lines"]["data"][0]["price"]["product"]
    #     amount = invoice_succeeded_object["amount_paid"]
    #     currency = invoice_succeeded_object["lines"]["data"][0]["currency"]
    #     metadata = invoice_succeeded_object["lines"]["data"][0]["metadata"]
    #     invoiceid = invoice_succeeded_object["id"]
    #     paymentintentid = invoice_succeeded_object["payment_intent"]
    #     createdat = event.created

    #     print("CUSTOMER< PRODUCT ID, AMOUNT, CURRENCY IS" , customerid, productid, amount, currency)
    #     mongoutil.make_payment_confirmation(customerid, productid, customer_user_map.get(customerid, None), amount, currency, invoiceid, paymentintentid, createdat, metadata.get("kickout_time", None))
    
    #     return  Response("{}", status = 200)
    if event.type == "charge.refund.updated":
        refund_updated_object = event.data.object
        print("REFUND STUFF BROTHER", refund_updated_object)
        #TODO REMOVE FROM DB
        #TODO HANDLE CURRENCY
        mongoutil.update_refund(refund_updated_object["payment_intent"], refund_updated_object["amount"])
        return  Response("{}", status = 200)
    return  Response("{}", status = 200)

