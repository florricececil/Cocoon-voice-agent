from flask import Flask, request
import os, asyncio
from livekit import api
from pyngrok import ngrok as ngrok_client

# Set ngrok auth token from env .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
auth_token = os.environ.get("NGROK_AUTH_TOKEN") or (
    open(env_path).read().split("NGROK_AUTH_TOKEN=")[1].split("\n")[0] if "NGROK_AUTH_TOKEN=" in open(env_path).read() else None
)
if auth_token:
    ngrok_client.set_auth_token(auth_token)

app = Flask(__name__)

LIVEKIT_URL = "wss://the-cocoon-j6a59lu9.livekit.cloud"
LIVEKIT_KEY = "APIGDzuEoqmZn8H"
LIVEKIT_SECRET = "lew8wxqLuaSZbTfkf0kaj1XfP4VSzCIredWzwQ9QuuB"
AGENT_NAME = "CA_JXVnMgpwh9Qp"
VERIFY_TOKEN = "CocoonVoice2025"

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "wrong", 403

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

@app.route("/")
def home():
    return "Cocoon Voice Live"

if __name__ == "__main__":
    try:
        public_url = ngrok_client.connect(8000)
        print(f"\n*** COPY THIS URL TO FACEBOOK: {public_url}/webhook ***\n")
    except Exception as e:
        print(f"\nNgrok tunnel skipped: {e}")
        print("Starting server without public tunnel - use localhost:8000")
    app.run(host="0.0.0.0", port=8000)
