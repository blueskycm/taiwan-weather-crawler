import time
from datetime import datetime, timedelta, timezone
import re
import os
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ✅ Google Sheets 設定
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "service_account.json"
SHEET_NAME = "weather_data"

# ✅ 台灣22縣市與 CID 對照表
CITY_CID_MAP = {
    "基隆市": "10017", "臺北市": "63", "新北市": "65", "桃園市": "68", "新竹市": "10018",
    "新竹縣": "10004", "苗栗縣": "10005", "臺中市": "66", "彰化縣": "10007", "南投縣": "10008",
    "雲林縣": "10009", "嘉義市": "10020", "嘉義縣": "10010", "臺南市": "67", "高雄市": "64",
    "屏東縣": "10013", "宜蘭縣": "10002", "花蓮縣": "10015", "臺東縣": "10014", "澎湖縣": "10016",
    "金門縣": "09020", "連江縣": "09007"
}

# ✅ 台灣時區設定
TAIWAN_TZ = timezone(timedelta(hours=8))
now = datetime.now(TAIWAN_TZ)

# ✅ 擷取單一縣市的天氣資料
def get_city_weather(city, cid):
    url = f"https://www.cwa.gov.tw/V8/C/W/County/County.html?CID={cid}"
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    driver.get(url)
    time.sleep(1)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    table = soup.find("table", {"id": "PC_Week_MOD"})
    if not table:
        raise Exception("找不到 PC_Week_MOD 表格")

    raw_dates = [th.get_text(strip=True).split()[0] for th in table.find("thead").find_all("th")[1:]]
    dates = []
    for d in raw_dates:
        try:
            match = re.match(r"(\d{2})/(\d{2})", d)
            if not match:
                raise ValueError("格式不符")
            month, day = map(int, match.groups())
            date_obj = datetime(now.year, month, day, tzinfo=TAIWAN_TZ)
            dates.append(date_obj.strftime("%Y-%m-%d"))
        except Exception as e:
            print(f"❌ 日期解析失敗: {d} -> {e}")
            dates.append("INVALID_DATE")

    day_row = table.find("tr", class_="day")
    night_row = table.find("tr", class_="night")
    feel_row = table.find("tr", id="lo-temp")
    uv_row = table.find("tr", id="ultra")

    feel_cells = feel_row.find_all("td") if feel_row else []
    uv_cells = uv_row.find_all("td") if uv_row else []

    feels = []
    for cell in feel_cells:
        span = cell.find("span", class_="tem-C")
        nums = re.findall(r"\d+", span.text) if span else []
        min_feel = int(nums[0]) if len(nums) > 0 else None
        max_feel = int(nums[1]) if len(nums) > 1 else None
        feels.append((min_feel, max_feel))

    uvs = []
    for cell in uv_cells:
        val = cell.find("strong")
        uv_index = int(val.text) if val and val.text.isdigit() else None
        uvs.append(uv_index)

    def extract_temp_weather(cells):
        result = []
        for cell in cells:
            span = cell.find("span", class_="tem-C")
            temps = re.findall(r"\d+", span.text) if span else []
            tmin = int(temps[0]) if len(temps) > 0 else None
            tmax = int(temps[1]) if len(temps) > 1 else None
            weather = cell.find("img")["title"] if cell.find("img") else "未知"
            result.append((tmin, tmax, weather))
        return result

    day_data = extract_temp_weather(day_row.find_all("td")) if day_row else []
    night_data = extract_temp_weather(night_row.find_all("td")) if night_row else []

    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for i in range(7):
        rows.append({
            "日期": dates[i] if i < len(dates) else "INVALID_DATE",
            "縣市": city,
            "白天min": day_data[i][0] if i < len(day_data) else None,
            "白天max": day_data[i][1] if i < len(day_data) else None,
            "白天天氣型態": day_data[i][2] if i < len(day_data) else "未知",
            "晚上min": night_data[i][0] if i < len(night_data) else None,
            "晚上max": night_data[i][1] if i < len(night_data) else None,
            "晚上天氣型態": night_data[i][2] if i < len(night_data) else "未知",
            "體感溫度min": feels[i][0] if i < len(feels) else None,
            "體感溫度max": feels[i][1] if i < len(feels) else None,
            "紫外線指數": uvs[i] if i < len(uvs) else None,
            "寫入時間戳記": timestamp
        })
    return rows

# ✅ 主流程：寫入 Google Sheets
def write_weather_to_sheets():
    print("🔄 擷取資料中...")
    all_data = []
    for city, cid in CITY_CID_MAP.items():
        try:
            all_data.extend(get_city_weather(city, cid))
            print(f"✅ {city} 完成")
        except Exception as e:
            print(f"⚠️ {city} 失敗：{e}")

    df = pd.DataFrame(all_data)

    # Google Sheets 授權
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

    # ✅ 找到下一個空白列
    col_values = sheet.col_values(1)
    next_row = len(col_values) + 1

    # ✅ 寫入資料（跳過標題列）
    rows = df.values.tolist()
    sheet.append_rows(rows, value_input_option="RAW")

    print("✅ 寫入完成，共寫入", len(rows), "筆資料")

# ✅ 執行主程式
if __name__ == "__main__":
    write_weather_to_sheets()
