import os
import time
import requests
from datetime import datetime
import telebot
import json
import logging
from hackcheck import HackCheckClient, SearchOptions, SearchFieldDomain

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

# Hàm kiểm tra domain sử dụng hackcheck-py
def check_domain_hc(client, domain):
    try:
        breaches = client.search(
            SearchOptions(
                field=SearchFieldDomain,
                query=domain,
            )
        )
        emails = {item.email for item in breaches.results if getattr(item, 'email', None)}
        logging.info(f"[DOMAIN: {domain}] [RESULTS: {len(breaches.results)}] [EMAILS: {emails}]")
        return emails
    except Exception as e:
        logging.error(f"[DOMAIN: {domain}] Lỗi khi gọi hackcheck-py: {e}")
        return set()

# Xử lý tệp tin được gửi đến
@bot.message_handler(content_types=['document'])
def handle_document(message):
    try:
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

        def process_domains(result_path):
            with open(result_path, 'w') as f:
                    f.write("")  # Tạo file trống
            logging.info(f"Đã tạo file kết quả: {result_path}")
            try:
                with HackCheckClient(HACKCHECK_API_KEY) as client:
                    # Xử lý từng domain tuần tự với delay 0.1s
                    for i, domain in enumerate(domains):
                        logging.info(f"Đang xử lý domain {i+1}/{len(domains)}: {domain}")
                        result = check_domain_hc(client, domain)
                        
                        if isinstance(result, set) and result:
                            with open(result_path, 'a') as f:
                                for email in result:
                                    f.write(email + '\n')
                        
                        # Delay 0.1s giữa các domain
                        time.sleep(0.1)
                    
                    logging.info(f"Hoàn thành xử lý {len(domains)} domains")
                    return True
                    
            except Exception as e:
                logging.error(f"Lỗi khi xử lý tệp: {e}")
                bot.reply_to(message, f"Lỗi khi xử lý tệp: {e}")
                return False

        result_filename = f"found_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        result_path = os.path.join(RESULTS_DIR, result_filename)
        logging.info(f"result_path: {result_path}")
        logging.info(f"Bắt đầu xử lý {len(domains)} domains")
        
        # Xử lý domains và kiểm tra kết quả
        success = process_domains(result_path)
        
        logging.info(f"Kết quả xử lý: success={success}, file_exists={os.path.exists(result_path)}")
        
        if success and os.path.exists(result_path):
            # Kiểm tra file có nội dung không
            with open(result_path, 'r') as f:
                content = f.read().strip()
            
            logging.info(f"Nội dung file: {len(content)} ký tự")
            
            if content:
                # Gửi file kết quả về cho user
                with open(result_path, 'rb') as result_file:
                    bot.send_document(reply_to_message_id=message.message_id, chat_id=message.chat.id, document=result_file, caption=f"Đã Xử lý thành công - Tìm thấy {len(content.split())} email")
            else:
                bot.reply_to(message, "Đã xử lý xong nhưng không tìm thấy email nào.")
        else:
            bot.reply_to(message, "Có lỗi xảy ra trong quá trình xử lý. Vui lòng thử lại.")
            
    except Exception as e:
        print(e)
        print(e.with_traceback())
        logging.error(f"Lỗi chung trong handle_document: {e}")
        bot.reply_to(message, f"Có lỗi xảy ra: {e}")


# Bắt đầu polling
bot.remove_webhook()
bot.infinity_polling()
