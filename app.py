import os
import time
import requests
from flask import Flask, request
from dotenv import load_dotenv
from threading import Thread, Event
import feedparser

# 환경 변수 로드
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("환경 변수가 제대로 설정되지 않았습니다. 환경 변수를 확인하세요.")

# POKT 데이터 조회 함수
def fetch_pokt_transactions():
    """POKT 네트워크에서 최근 트랜잭션 데이터를 가져옴"""
    try:
        # 실제 POKT API 필요: https://docs.pokt.network/gateways/host-a-gateway/api-endpoints
        # 공용 API 없음, Pocket Scan 지원팀 문의 권장
        print("POKT API: 실제 엔드포인트 필요. 더미 데이터로 테스트.")
        return [
            {
                "hash": "abc123",
                "stdTx": {
                    "msg": {
                        "value": {
                            "amount": 150_000_000_000,  # 150,000 POKT (uPOKT)
                            "from_address": "0x1111...",
                            "to_address": "0x1234..."
                        }
                    },
                    "time": "2025-05-29T09:20:00"
                }
            }
        ]
    except requests.RequestException as e:
        print(f"POKT 트랜잭션 조회 실패: {e}")
        return []

def detect_large_movements(transactions, threshold=100000):
    """대량 이동(threshold 이상) 감지"""
    large_movements = []
    for tx in transactions:
        try:
            amount = float(tx.get("stdTx", {}).get("msg", {}).get("value", {}).get("amount", 0)) / 1_000_000
            if amount >= threshold:
                large_movements.append({
                    "tx_hash": tx.get("hash"),
                    "amount": amount,
                    "from": tx.get("stdTx", {}).get("msg", {}).get("value", {}).get("from_address"),
                    "to": tx.get("stdTx", {}).get("msg", {}).get("value", {}).get("to_address"),
                    "time": tx.get("time")
                })
        except (ValueError, TypeError, KeyError):
            continue
    return large_movements

def check_exchange_wallet(address):
    """주소가 거래소 지갑인지 확인"""
    known_exchanges = {
        "0x1234...": "Binance",
        "0x5678...": "Coinbase",
        # 실제 주소 추가 필요
    }
    return known_exchanges.get(address, "Unknown")

def fetch_migration_news():
    """POKT RSS 피드에서 Shannon 업그레이드 뉴스 확인"""
    try:
        feed = feedparser.parse("https://pocket.network/feed")
        for entry in feed.entries[:5]:
            if "shannon" in entry.title.lower() or "upgrade" in entry.title.lower():
                return f"📰 Shannon 업그레이드 뉴스: {entry.title}\n링크: {entry.link}"
        return None
    except Exception as e:
        print(f"RSS 피드 조회 실패: {e}")
        return None

# 텔레그램 메시지 전송
def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"메시지 전송 실패: {e}")
        return {"ok": False, "description": str(e)}

# POKT 모니터링 스레드
monitor_stop_event = Event()

def monitor_pokt():
    """주기적으로 POKT 데이터 모니터링"""
    while not monitor_stop_event.is_set():
        transactions = fetch_pokt_transactions()
        large_movements = detect_large_movements(transactions)
        for movement in large_movements:
            to_exchange = check_exchange_wallet(movement["to"])
            message = (
                f"🚨 POKT 대량 이동 감지!\n"
                f"금액: {movement['amount']:.2f} POKT\n"
                f"보낸 주소: {movement['from']}\n"
                f"받은 주소: {movement['to']} ({to_exchange})\n"
                f"시간: {movement['time']}\n"
                f"Tx Hash: {movement['tx_hash']}"
            )
            send_telegram_message(TELEGRAM_CHAT_ID, message)

        news = fetch_migration_news()
        if news:
            send_telegram_message(TELEGRAM_CHAT_ID, news)

        time.sleep(300)  # 5분마다 체크

# Flask 앱 설정
app = Flask(__name__)

@app.route("/")
def home():
    return "POKT 추적 봇 서버 동작 중입니다."

@app.route("/test", methods=["GET"])
def test():
    send_telegram_message(TELEGRAM_CHAT_ID, "✅ 테스트 메시지: 서버가 잘 작동 중입니다.")
    return "텔레그램 메시지 전송 완료!"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        print("Invalid request received")
        return "Invalid request", 400
    
    print(f"Received update: {update}")
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        if text == "/start":
            send_telegram_message(chat_id, "안녕하세요! POKT 추적 봇입니다. /help로 도움말을 확인하세요.")
        elif text == "/help":
            send_telegram_message(chat_id, "사용 가능한 명령어:\n/start - 봇 시작\n/help - 도움말\n/status - 서버 상태 확인\n/monitor - POKT 모니터링 시작\n/stop - 모니터링 중지")
        elif text == "/status":
            send_telegram_message(chat_id, "서버 상태: 정상 작동 중")
        elif text == "/monitor":
            if not monitor_stop_event.is_set():
                send_telegram_message(chat_id, "POKT 모니터링이 이미 실행 중입니다.")
            else:
                monitor_stop_event.clear()
                Thread(target=monitor_pokt, daemon=True).start()
                send_telegram_message(chat_id, "POKT 모니터링을 시작했습니다.")
        elif text == "/stop":
            monitor_stop_event.set()
            send_telegram_message(chat_id, "POKT 모니터링을 중지했습니다.")
        else:
            send_telegram_message(chat_id, f"받은 메시지: {text}")
    return "ok", 200

# 텔레그램 웹훅 설정
def set_telegram_webhook():
    port = int(os.getenv("PORT", 10000))
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = {"url": webhook_url}
    response = requests.post(url, json=payload)
    result = response.json()
    print(f"Webhook 설정 응답: {result}")
    if not result.get("ok"):
        print(f"Webhook 설정 실패: {result.get('description')}")
        return False
    return True

# 서버 실행
if __name__ == "__main__":
    if set_telegram_webhook():
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)), debug=False)
    else:
        print("서버를 시작하지 않습니다. 웹훅 설정을 확인하세요.")