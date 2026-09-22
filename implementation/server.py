from flask import Flask, request
import os, asyncio
from livekit import api
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_SECRET = os.getenv("LIVEKIT_API_SECRET")
AGENT_NAME = os.getenv("AGENT_NAME", "Wish")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "CocoonVoice2025")

@app.route("/")
def home():
    return "Cocoon Voice Live - OK"

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def incoming():
    try:
        data = request.json
        val = data['entry'][0]['changes'][0]['value']
        if 'messages' in val:
            from_num = val['messages'][0]['from']
            print(f"WhatsApp from {from_num}")
            async def dispatch():
                lk = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_KEY, LIVEKIT_SECRET)
                room = f"whatsapp-{from_num}"
                await lk.room.create_room(api.CreateRoomRequest(name=room))
                await lk.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        agent_name=AGENT_NAME,
                        room=room,
                        metadata=from_num
                    )
                )
                await lk.aclose()
            asyncio.run(dispatch())
    except Exception as e:
        print("Error:", e)
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)