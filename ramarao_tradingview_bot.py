import imaplib
import email
import datetime

from dateutil import tz
# Auto-detect zones
from_zone = tz.tzutc()
to_zone = tz.tzlocal()

import yaml
import os
import time
import ccxt

# load configfile
configfile = yaml.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')), Loader=yaml.BaseLoader)

timeframes = {'1m': 60*1000,
              '5m': 5*60*1000,
              '15m': 15*60*1000,
              '30m': 30*60*1000,
              '1h': 60*60*1000,
              '3h': 3*60*60*1000,
              '6h': 6*60*60*1000,
              '12h': 12*60*60*1000,
              '1d': 24*60*60*1000,
              '1w': 7*24*60*60*1000,
              '2w': 14*24*60*60*1000,
              '1M': None}

timeframe = configfile['timeframe']
indicator_checks_per_timeframe = int(configfile['indicator_checks_per_timeframe'])
usd_amount = int(configfile['usd_amount'])
stop_percent = float(configfile['prod_stop_percent_distance'])
api_sleep = int(configfile['api_sleep'])

# create TEST instance
bitmex_test = ccxt.bitmex({
    'apiKey': configfile['TEST_KEY_PLACE_CANCEL_NO_WITHDRAW'],
    'secret': configfile['TEST_SECRET_PLACE_CANCEL_NO_WITHDRAW'],
})
bitmex_test.urls['api'] = bitmex_test.urls['test']
# TEST default STOP and TAKE PROFIT distance
test_stop_percent_distance = float(configfile['test_stop_percent_distance'])
test_take_profit_percent_distance = float(configfile['test_take_profit_percent_distance'])

# create PROD instance
bitmex_prod = ccxt.bitmex({
    'apiKey': configfile['PROD_KEY_PLACE_CANCEL_NO_WITHDRAW'],
    'secret': configfile['PROD_SECRET_PLACE_CANCEL_NO_WITHDRAW'],
})
# PROD default STOP and TAKE PROFIT distance
prod_stop_percent_distance = float(configfile['prod_stop_percent_distance'])
prod_take_profit_percent_distance = float(configfile['prod_take_profit_percent_distance'])

# used for BUY signal
acc_1_u = configfile['email_account_1_username']
acc_1_p = configfile['email_account_1_password']

# used for SELL signal
acc_2_u = configfile['email_account_2_username']
acc_2_p = configfile['email_account_2_password']

smtp_server = configfile['smtp_server']
smtp_port= configfile['smtp_port']

def readmail(from_email, from_pwd, smtp_server, smtp_port):
	"""checks for email with BUY or SELL signal and returns BUY or SELL and datetime object of time received"""
	try:
		mail = imaplib.IMAP4_SSL(smtp_server)
		mail.login(from_email, from_pwd)
		mail.select('inbox')
		result, data = mail.search(None, '(FROM "noreply@tradingview.com")')
		mail_ids = data[0]
		id_list = mail_ids.split()
		first_email_id = id_list[0]
		latest_email_id = id_list[-1] #most recent email
		result,data = mail.fetch(latest_email_id, "(RFC822)")
		raw_email = data[0][1]
		email_message = email.message_from_string(str(raw_email))
		timestamp_received_str = raw_email.decode('utf-8').split('Date: ')[1][:150].split(', ')[1].split(' +')[0]
		timestamp_received_obj = datetime.datetime.strptime(timestamp_received_str, '%d %b %Y %H:%M:%S')
		timestamp_received_obj = timestamp_received_obj.replace(tzinfo=from_zone)
		timestamp_received_obj = timestamp_received_obj.astimezone(to_zone)
		return raw_email.decode('utf-8').split('YOUR XBTUSD alert was triggered: ')[1][0], timestamp_received_obj

	except Exception as e:
		print('=== ERROR ON ACCOUNT: ' + str(from_email) + ': ' + str(e))
		return False, datetime.datetime.strptime('2019-08-10 09:00:00', '%Y-%m-%d %H:%M:%S').astimezone(to_zone)

# get BUY or SELL signal and according datetime objects of time received
def bot():

	start_timestamp = time.time()

	buy = False
	buy_signal, buy_datetime = readmail(acc_1_u, acc_1_p, smtp_server, smtp_port)
	sell = False
	sell_signal, sell_datetime = readmail(acc_2_u, acc_2_p, smtp_server, smtp_port)
	# if BUY signal more recent then BUY
	if buy_datetime > sell_datetime:
		buy = True
		sell = False
	# if SELL signal more recent then SELL
	elif buy_datetime < sell_datetime:
		buy = False
		sell = True
	else:
		buy = False
		sell = False

	# check current position
	prod_position = 0
	prod_position_check = bitmex_prod.private_get_position({'symbol': 'BTCUSD'})
	time.sleep(api_sleep)
	if len(prod_position_check) > 0:
		prod_position = int(prod_position_check[0]['currentQty'])
	else:
		pass

	# if no open position go long or short and place stop(s)
	if prod_position == 0:
		if buy == True:
			# go long
			position_long = bitmex_prod.create_order(symbol='BTC/USD', type='market', side='buy', amount=usd_amount, price=None, params={})
			time.sleep(api_sleep)
			average_entry_price_long = position_long['average']
			# place stop below long entry
			stop_for_long_position = bitmex_prod.create_order(symbol='BTC/USD', type='stop', side='sell', amount=usd_amount, price=None, params={'stopPx': int(average_entry_price_long * float(1 - (stop_percent / 100)))})
			time.sleep(api_sleep)
		if sell == True:
			# go short
			position_short = bitmex_prod.create_order(symbol='BTC/USD', type='market', side='sell', amount=usd_amount, price=None, params={})
			time.sleep(api_sleep)
			average_entry_price_short = position_short['average']
			# place stop above short entry
			stop_for_short_position = bitmex_prod.create_order(symbol='BTC/USD', type='stop', side='buy', amount=usd_amount, price=None, params={'stopPx': int(average_entry_price_short * float(1 + (stop_percent / 100)))})
			time.sleep(api_sleep)

	# if current position == long and buy == True then do nothing
	elif prod_position > 0 and buy == True:
		pass

	# if current position == long and sell == True then close all positions and orders and open short position with stop(s)
	elif prod_position > 0 and sell == True:
		# close open position
		bitmex_prod.private_post_order_closeposition({'symbol': 'BTCUSD'})
		time.sleep(api_sleep)
		# cancel all open orders
		open_orders = bitmex_prod.fetch_open_orders()
		for open_order in open_orders:
			bitmex_prod.cancel_order(id=open_order['id'])
			time.sleep(api_sleep)
		# go short
		position_short = bitmex_prod.create_order(symbol='BTC/USD', type='market', side='sell', amount=usd_amount, price=None, params={})
		time.sleep(api_sleep)
		print(position_short)
		average_entry_price_short = position_short['average']
		# place stop above short entry
		stop_for_short_position = bitmex_prod.create_order(symbol='BTC/USD', type='stop', side='buy', amount=usd_amount, price=None, params={'stopPx': int(average_entry_price_short * float(1 + (stop_percent / 100)))})
		time.sleep(api_sleep)
	
	# if current position == short and sell == True then do nothing
	elif prod_position < 0 and sell == True:
		pass
	
	# if current position == short and buy == True then close all positions and orders and open long position with stop(s)
	elif prod_position < 0 and buy == True:
		# close open position
		bitmex_prod.private_post_order_closeposition({'symbol': 'BTCUSD'})
		time.sleep(api_sleep)
		# cancel all open orders
		open_orders = bitmex_prod.fetch_open_orders()
		for open_order in open_orders:
			bitmex_prod.cancel_order(id=open_order['id'])
			time.sleep(api_sleep)
		# go long
		position_long = bitmex_prod.create_order(symbol='BTC/USD', type='market', side='buy', amount=usd_amount, price=None, params={})
		time.sleep(api_sleep)
		print(position_long)
		average_entry_price_long = position_long['average']
		# place stop below long entry
		stop_for_long_position = bitmex_prod.create_order(symbol='BTC/USD', type='stop', side='sell', amount=usd_amount, price=None, params={'stopPx': int(average_entry_price_long * float(1 - (stop_percent / 100)))})
		time.sleep(api_sleep)

	# in any other case do nothing
	else:
		pass

	# check position after latest signal
	prod_position_post = 0
	prod_position_check_post = bitmex_prod.private_get_position({'symbol': 'BTCUSD'})
	time.sleep(api_sleep)
	if len(prod_position_check_post) > 0:
		prod_position_post = int(prod_position_check_post[0]['currentQty'])
	else:
		pass

	# check PnL from initial deposit of 1095034 sats
	#wallet_history_prod = bitmex_prod.private_get_user_wallBTCistory()
	#time.sleep(api_sleep)
	#balances = []
	#for row in wallet_history_prod:
	#	balances.append(row['walletBalance'])
	#balances = balances[::-1]
	#balances = balances[balances.index(1095034):]

	print('===================')
	print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
	print('Timeframe:\t\t' + str(timeframe))
	print('Runs per Timeframe:\t' + str(indicator_checks_per_timeframe))
	print('Position:\t\t' + str(prod_position_post))
	#print('Position PnL:\t\t' + str(round(float(prod_position_check_post[0]['unrealisedPnlPcnt']) * 100, 2)) + '%')
	#print('Total PnL:\t\t' + str(round((balances[-1] - balances[0]) * 100 / balances[0], 2)) + '%')
	print('Buy:\t\t\t' + str(buy) + ' ' + str(buy_datetime))
	print('Sell:\t\t\t' + str(sell) + ' ' + str(sell_datetime))

# 	time.sleep(((int(timeframes[timeframe])/indicator_checks_per_timeframe)/1000) - (time.time() - start_timestamp))

# n_loops = 0
# loop_history = []

# def run_bot():

#     global n_loops
#     global loop_history

#     while True:
#         try:
#             bot()
#             n_loops += 1
#             print('No ERROR since ' + str(n_loops) + ' runs')
#         except Exception as e:
#             loop_history.append(n_loops)
#             print(e)
#             print('===== ERROR =====')
#             print('Loops to ERROR: ' + str(n_loops))
#             print(loop_history)
#             n_loops = 0
#             time.sleep(60)
#         print()

# run_bot()
while True:
    bot()
