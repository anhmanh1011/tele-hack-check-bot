import os
import time
import requests
from datetime import datetime
import telebot
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# Cấu hình rate limiting
MAX_CONCURRENT_REQUESTS = 3  # Xử lý 3 request đồng thời
REQUEST_DELAY = 0.5  # 0.5s giữa các request (cho phép 2 request/giây)

# Biến kiểm soát trạng thái xử lý
is_processing = False
current_processing_file = None

# Xử lý lệnh /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Chào bạn! Gửi cho tôi một tệp TXT chứa danh sách domain (mỗi dòng một domain). Tôi sẽ kiểm tra từng domain trên HackCheck API và trả về danh sách domain đã được tìm thấy.")

# Xử lý lệnh /status
@bot.message_handler(commands=['status'])
def check_status(message):
    global is_processing, current_processing_file
    if is_processing:
        bot.reply_to(message, f"⚠️ Bot đang xử lý file: {current_processing_file}\nVui lòng chờ hoàn thành trước khi upload file mới.")
    else:
        bot.reply_to(message, "✅ Bot sẵn sàng nhận file mới.")

# Hàm kiểm tra domain trực tiếp với HackCheck API
def check_domain_hc(domain):
    time.sleep(REQUEST_DELAY)
    try:
        # URL theo format CURL: https://api.hackcheck.io/search/your-API-key/domain/domain.com
        url = f"https://api.hackcheck.io/search/{HACKCHECK_API_KEY}/domain/{domain}"
        
        start_time = time.time()
        logging.info(f"[DOMAIN: {domain}] Bắt đầu gọi API")
        
        # Gọi API với timeout 15 giây (giảm từ 30s)
        response = requests.get(url, timeout=15)
        
        end_time = time.time()
        request_time = end_time - start_time
        
        if response.status_code == 200:
            data = response.json()
            
            # Kiểm tra cấu trúc response
            if 'results' in data and isinstance(data['results'], list):
                emails = set()
                for item in data['results']:
                    if isinstance(item, dict) and 'email' in item and item['email']:
                        emails.add(item['email'])
                
                logging.info(f"[DOMAIN: {domain}] [TIME: {request_time:.3f}s] [RESULTS: {len(data['results'])}] [EMAILS: {emails}]")
                return emails
            else:
                logging.warning(f"[DOMAIN: {domain}] [TIME: {request_time:.3f}s] Response không có cấu trúc 'results': {data}")
                return set()
                
        elif response.status_code == 429:
            logging.warning(f"[DOMAIN: {domain}] [TIME: {request_time:.3f}s] Rate limit hit (429)")
            return set()
        elif response.status_code == 401:
            logging.error(f"[DOMAIN: {domain}] [TIME: {request_time:.3f}s] API key không hợp lệ (401)")
            return set()
        else:
            logging.error(f"[DOMAIN: {domain}] [TIME: {request_time:.3f}s] HTTP {response.status_code}: {response.text}")
            return set()
            
    except requests.exceptions.Timeout:
        logging.error(f"[DOMAIN: {domain}] Timeout khi gọi API (>15s)")
        return set()
    except requests.exceptions.RequestException as e:
        logging.error(f"[DOMAIN: {domain}] Lỗi network: {e}")
        return set()
    except json.JSONDecodeError as e:
        logging.error(f"[DOMAIN: {domain}] Lỗi parse JSON: {e}")
        return set()
    except Exception as e:
        logging.error(f"[DOMAIN: {domain}] Lỗi không xác định: {e}")
        return set()

# Xử lý tệp tin được gửi đến
@bot.message_handler(content_types=['document'])
def handle_document(message):
    global is_processing, current_processing_file
    
    # Kiểm tra xem có đang xử lý file khác không
    if is_processing:
        bot.reply_to(message, f"❌ Bot đang xử lý file: {current_processing_file}\nVui lòng chờ hoàn thành trước khi upload file mới.\nSử dụng /status để kiểm tra trạng thái.")
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        if not file_info.file_path:
            bot.reply_to(message, "Không thể lấy đường dẫn tệp từ Telegram.")
            return
        downloaded_file = bot.download_file(file_info.file_path)
        file_path = os.path.join(DOWNLOAD_DIR, message.document.file_name)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        # Đánh dấu đang xử lý
        is_processing = True
        current_processing_file = message.document.file_name
        
        bot.reply_to(message, f"✅ Đã tải tệp: {message.document.file_name}\n🔄 Bắt đầu xử lý...")
        file_name = message.document.file_name
        print('file_name', file_name)
        
        # Đọc danh sách tên miền từ tệp
        with open(file_path, 'r') as f:
            domains = [line.strip() for line in f if line.strip()]

        def process_domains_parallel(result_path):
            global is_processing, current_processing_file
            
            # Tạo file kết quả trước khi xử lý
            with open(result_path, 'w') as f:
                f.write("")  # Tạo file trống
            logging.info(f"Đã tạo file kết quả: {result_path}")
            
            try:
                all_emails = set()
                processed_count = 0
                
                # Xử lý song song với ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
                    # Tạo futures cho tất cả domains
                    future_to_domain = {executor.submit(check_domain_hc, domain): domain for domain in domains}
                    
                    # Xử lý kết quả khi hoàn thành
                    for future in as_completed(future_to_domain):
                        domain = future_to_domain[future]
                        processed_count += 1
                        
                        try:
                            result = future.result()
                            if isinstance(result, set) and result:
                                all_emails.update(result)
                                # Ghi ngay khi có kết quả
                                with open(result_path, 'a') as f:
                                    for email in result:
                                        f.write(email + '\n')
                            
                            # Log tiến độ mỗi 10 domains
                            if processed_count % 10 == 0:
                                logging.info(f"Tiến độ: {processed_count}/{len(domains)} domains")
                            
                        except Exception as e:
                            logging.error(f"Lỗi khi xử lý domain {domain}: {e}")
                
                logging.info(f"Hoàn thành xử lý {len(domains)} domains, tìm thấy {len(all_emails)} emails")
                return True
                
            except Exception as e:
                print(f"Lỗi: {e}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
                logging.error(f"Lỗi khi xử lý tệp: {e}")
                bot.reply_to(message, f"Lỗi khi xử lý tệp: {e}")
                return False
            finally:
                # Reset trạng thái xử lý
                is_processing = False
                current_processing_file = None

        result_filename = f"found_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        result_path = os.path.join(RESULTS_DIR, result_filename)
        logging.info(f"result_path: {result_path}")
        logging.info(f"Bắt đầu xử lý {len(domains)} domains với {MAX_CONCURRENT_REQUESTS} workers")
        
        start_time = time.time()
        
        # Xử lý domains song song
        success = process_domains_parallel(result_path)
        
        total_time = time.time() - start_time
        
        logging.info(f"Kết quả xử lý: success={success}, file_exists={os.path.exists(result_path)}, total_time={total_time:.2f}s")
        
        if success and os.path.exists(result_path):
            # Kiểm tra file có nội dung không
            with open(result_path, 'r') as f:
                content = f.read().strip()
            
            logging.info(f"Nội dung file: {len(content)} ký tự")
            
            if content:
                # Gửi file kết quả về cho user
                with open(result_path, 'rb') as result_file:
                    bot.send_document(reply_to_message_id=message.message_id, chat_id=message.chat.id, document=result_file, caption=f"✅ Đã xử lý thành công!\n📧 Tìm thấy {len(content.split())} email\n⏱️ Thời gian: {total_time:.2f}s\n📁 File: {file_name}")
            else:
                bot.reply_to(message, f"✅ Đã xử lý xong trong {total_time:.2f}s nhưng không tìm thấy email nào.\n📁 File: {file_name}")
        else:
            bot.reply_to(message, f"❌ Có lỗi xảy ra trong quá trình xử lý file: {file_name}\nVui lòng thử lại.")
            
    except Exception as e:
        print(f"Lỗi chung: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        logging.error(f"Lỗi chung trong handle_document: {e}")
        bot.reply_to(message, f"❌ Có lỗi xảy ra: {e}")
        
        # Reset trạng thái xử lý nếu có lỗi
        global is_processing, current_processing_file
        is_processing = False
        current_processing_file = None

# Bắt đầu polling
bot.remove_webhook()
bot.infinity_polling()
