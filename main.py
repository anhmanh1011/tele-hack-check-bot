import os
from datetime import datetime
import psycopg2
from urllib.parse import urlparse
import telebot

# Thay thế 'YOUR_BOT_TOKEN' bằng token thực tế của bạn từ BotFather
API_TOKEN = '7888902716:AAFmgRgDaYiz8OcfqlRLgNwf13KfZ0z7yak'
bot = telebot.TeleBot(API_TOKEN)

# Thư mục lưu trữ tệp tải về
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
db_url = os.environ.get("DATABASE_URL")
print('db_url' + db_url)
# db_url = 'postgresql://postgres:RJjCiHGBSvgkbgzGhtubrgMipdnsjaFa@hopper.proxy.rlwy.net:47525/railway'

# Parse the URL
result = urlparse(db_url)

# Connect to PostgreSQL
conn = psycopg2.connect(
    dbname=result.path.lstrip("/"),
    user=result.username,
    password=result.password,
    host=result.hostname,
    port=result.port
)

# Xử lý lệnh /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Chào bạn! Gửi cho tôi một tệp tin và tôi sẽ tải nó về.")

# Xử lý tệp tin được gửi đến
@bot.message_handler(content_types=['document'])
def handle_document(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        file_path = os.path.join(DOWNLOAD_DIR, message.document.file_name)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        bot.reply_to(message, f"Đã tải tệp: {message.document.file_name}")
        file_name = message.document.file_name

        # Trích xuất ngày thu thập từ tên tệp (giả sử định dạng: domains_YYYYMMDD.txt)
        try:
            date_str = file_name.split('.')[0]
            collected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (IndexError, ValueError):
            collected_date = datetime.now().date()

        print(collected_date)
        # Đọc danh sách tên miền từ tệp
        with open(file_path, 'r') as f:
            domains = [line.strip() for line in f if line.strip()]

        insert_query = """
            INSERT INTO domains (name, collected_date)
            VALUES (%s, %s)
            ON CONFLICT (name) DO NOTHING;
        """
        data = [(domain, collected_date) for domain in domains]
        cur = conn.cursor()
        rows_before = cur.rowcount
        cur.executemany(insert_query, data)
        conn.commit()
        rows_after = cur.rowcount
        inserted = rows_after if rows_after != -1 else len(domains)
        bot.reply_to(message, f"Đã insert thành công : {inserted} domains")
    except Exception as e:
        print(e)
        e.print_exc()
        bot.reply_to(message, "Có lỗi xảy ra khi tải tệp.")

# Bắt đầu polling
bot.infinity_polling()
