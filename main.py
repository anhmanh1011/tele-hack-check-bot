import os
import time
import requests
from datetime import datetime
import telebot
import json
import asyncio
import aiohttp
import logging
import math

# Đọc cấu hình từ file config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)
API_TOKEN = config['API_TOKEN']
HACKCHECK_API_KEY = config['HACKCHECK_API_KEY']
bot = telebot.TeleBot(API_TOKEN)

# Thư mục lưu trữ tệp tải về
DOWNLOAD_DIR = 'downloads'
RESULTS_DIR = 'results'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Thiết lập logging
logging.basicConfig(filename='api.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Xử lý lệnh /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Chào bạn! Gửi cho tôi một tệp TXT chứa danh sách domain (mỗi dòng một domain). Tôi sẽ kiểm tra từng domain trên HackCheck API và trả về danh sách domain đã được tìm thấy.")

# Thay thế hàm kiểm tra domain bằng async
async def check_domain(session, semaphore, domain, api_key):
    url = f"https://api.hackcheck.io/search/{api_key}/domain/{domain}"
    async with semaphore:
        try:
            async with session.get(url, timeout=10) as response:
                resp_text = await response.text()
                logging.info(f"[DOMAIN: {domain}] [STATUS: {response.status}] [RESPONSE: {resp_text}]")
                if response.status == 200:
                    try:
                        json_data = json.loads(resp_text)
                        emails = {item['email'] for item in json_data.get('results', []) if 'email' in item and item['email']}
                        return emails
                    except Exception as e:
                        logging.error(f"[DOMAIN: {domain}] Lỗi parse JSON: {e}")
                        return 'json_error'
                elif response.status == 401:
                    logging.error(f"[DOMAIN: {domain}] Lỗi 401: IP hoặc API key không hợp lệ")
                    return 'unauthorized'
                else:
                    logging.error(f"[DOMAIN: {domain}] Lỗi không xác định, status: {response.status}")
                    return 'error'
        except asyncio.TimeoutError:
            logging.error(f"[DOMAIN: {domain}] Timeout khi gọi API")
            return 'timeout'
        except aiohttp.ClientError as e:
            logging.error(f"[DOMAIN: {domain}] Lỗi ClientError: {e}")
            return 'client_error'
        except Exception as e:
            logging.error(f"[DOMAIN: {domain}] Lỗi không xác định: {e}")
            return set()

# Xử lý tệp tin được gửi đến
@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_info = bot.get_file(message.document.file_id)
    if not file_info.file_path:
        bot.reply_to(message, "Không thể lấy đường dẫn tệp từ Telegram.")
        return
    downloaded_file = bot.download_file(file_info.file_path)
    # print('Downloaded to {}'.format(downloaded_file))
    file_path = os.path.join(DOWNLOAD_DIR, message.document.file_name)
    with open(file_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    bot.reply_to(message, f"Đã tải tệp: {message.document.file_name}")
    file_name = message.document.file_name
    print('file_name', file_name)
    # Đọc danh sách tên miền từ tệp
    with open(file_path, 'r') as f:
        domains = [line.strip() for line in f if line.strip()]

    found_domains = set()
    semaphore = asyncio.Semaphore(10)

    async def process_domains():
        async with aiohttp.ClientSession() as session:
            batch_size = 10
            total = len(domains)
            for i in range(0, total, batch_size):
                batch = domains[i:i+batch_size]
                tasks = [check_domain(session, semaphore, domain, HACKCHECK_API_KEY) for domain in batch]
                results = await asyncio.gather(*tasks)
                for idx, result in enumerate(results):
                    if result == 'unauthorized':
                        bot.reply_to(message, "IP hoặc API key không hợp lệ")
                        return None
                    elif result == 'error':
                        bot.reply_to(message, f"Lỗi không xác định với domain: {batch[idx]}")
                        continue
                    elif result == 'timeout':
                        bot.reply_to(message, f"Timeout khi kiểm tra domain: {batch[idx]}")
                        continue
                    elif result == 'client_error':
                        bot.reply_to(message, f"Lỗi mạng khi kiểm tra domain: {batch[idx]}")
                        continue
                    elif result == 'json_error':
                        bot.reply_to(message, f"Lỗi dữ liệu trả về từ API với domain: {batch[idx]}")
                        continue
                    elif isinstance(result, set):
                        found_domains.update(result)
                await asyncio.sleep(1)  # Chờ 1 giây giữa các batch
        return True

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ok = loop.run_until_complete(process_domains())
    if not ok:
        return

    # Ghi kết quả vào file
    result_filename = f"found_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    result_path = os.path.join(RESULTS_DIR, result_filename)
    with open(result_path, 'w') as f:
        for email in found_domains:
            f.write(email + '\n')

    # Gửi file kết quả về cho user
    with open(result_path, 'rb') as result_file:
        bot.send_document(reply_to_message_id=message.message_id, chat_id=message.chat.id, document=result_file, caption=f"Các domain đã được tìm thấy: {len(found_domains)}")


# Bắt đầu polling
bot.remove_webhook()
bot.infinity_polling()
