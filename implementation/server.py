from flask import Flask, request
import os

# Optional import - won't crash if missing
try:
    import requests
except:
    requests = None

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "CocoonVoice2025")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

@app.route('/')
def home():
    return "Cocoon Voice Agent is running", 200

@app.route('/privacy')
def privacy():
    return "Privacy Policy for Cocoon Voice Agent: We do not store personal data. WhatsApp messages are processed to provide real estate responses and are not shared.", 200

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True)
    print(f"WEBHOOK RECEIVED: {data}", flush=True)
    # Just return OK to keep Facebook happy - your bot logic can be added after
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)