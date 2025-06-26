import os
import time
import requests
from datetime import datetime
import telebot
import json

# Thay thế 'YOUR_BOT_TOKEN' bằng token thực tế của bạn từ BotFather
API_TOKEN = '7624114226:AAH5v2z_BZ8B9S1yefOfBWGIgyPoEKk1DjI'
HACKCHECK_API_KEY = 'hc_r3sroj6tmv9ftgtxn95wujjf'  # <-- Replace with your real API key
bot = telebot.TeleBot(API_TOKEN)

# Thư mục lưu trữ tệp tải về
DOWNLOAD_DIR = 'downloads'
RESULTS_DIR = 'results'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Xử lý lệnh /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Chào bạn! Gửi cho tôi một tệp TXT chứa danh sách domain (mỗi dòng một domain). Tôi sẽ kiểm tra từng domain trên HackCheck API và trả về danh sách domain đã được tìm thấy.")


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
    for idx, domain in enumerate(domains):
        url = f"https://api.hackcheck.io/search/{HACKCHECK_API_KEY}/domain/{domain}"
        try:
            response = requests.get(url, timeout=10)
            print('response', response)
            if response.status_code == 200:
                data = response.content
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                json_data = json.loads(data)
                # Extract emails from the 'results' list
                emails = {item['email'] for item in json_data.get('results', []) if 'email' in item and item['email']}
                found_domains.update(emails)
        except Exception as e:
            print(f"Error checking domain {domain}: {e}")
        # Rate limit: 10 requests per second
      
        time.sleep(0.1)  # ~10 req/sec

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
