import requests
import json
import os
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad, pad
from base64 import b64decode, b64encode
import base64

from models import db, RequestedBatch

app = Flask(__name__)
CORS(app)

# Vercel-compatible initialization: Move config into app context
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or "sqlite:///fallback.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
db.init_app(app)

# Create tables ONLY if they don't exist, and do it safely
def ensure_db():
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        print(f"Lazy DB init warning: {e}")

# Call this at the start of routes that need DB

# Configuration
API_URL = "https://application.utkarshapp.com/index.php/data_model"
COMMON_KEY = b"%!^F&^$)&^$&*$^&"
COMMON_IV = b"#*v$JvywJvyJDyvJ"
key_chars = "%!F*&^$)_*%3f&B+"
iv_chars = "#*$DJvyw2w%!_-$@"

HEADERS = {
    "Authorization": "Bearer 152#svf346t45ybrer34yredk76t",
    "Content-Type": "text/plain; charset=UTF-8",
    "devicetype": "1",
    "host": "application.utkarshapp.com",
    "lang": "1",
    "user-agent": "okhttp/4.9.0",
    "userid": "0",
    "version": "152"
}

# Session state
session = requests.Session()
user_auth = {
    "token": None,
    "jwt": None,
    "userid": "0",
    "key": None,
    "iv": None,
    "logged_in": False,
    "csrf": None,
    "login_time": 0
}

# URLs
base_url = 'https://online.utkarsh.com/'
login_url = 'https://online.utkarsh.com/web/Auth/login'
tiles_data_url = 'https://online.utkarsh.com/web/Course/tiles_data'
layer_two_data_url = 'https://online.utkarsh.com/web/Course/get_layer_two_data'
meta_source_url = '/meta_distributer/on_request_meta_source'

REQUESTED_BATCHES_FILE = "requested_batches.json"

from supabase import create_client, Client

# Supabase configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def load_requested_batches():
    ensure_db()
    if not supabase:
        with app.app_context():
            batches = RequestedBatch.query.all()
            return [b.batch_id for b in batches]
    try:
        response = supabase.table('requested_batch').select('batch_id').execute()
        if hasattr(response, 'data') and response.data:
            return [row['batch_id'] for row in response.data]
        return []
    except Exception as e:
        print(f"Supabase load error: {e}")
        return []

def save_batch_to_db(batch_id, title=None, course_name=None):
    ensure_db()
    bid_str = str(batch_id)
    # Local DB update
    with app.app_context():
        existing = RequestedBatch.query.filter_by(batch_id=bid_str).first()
        if not existing:
            new_batch = RequestedBatch()
            new_batch.batch_id = bid_str
            new_batch.title = title
            new_batch.course_name = course_name
            db.session.add(new_batch)
        else:
            if title: existing.title = title
            if course_name: existing.course_name = course_name
        db.session.commit()
    
    # Supabase update
    if supabase:
        try:
            data = {"batch_id": bid_str}
            if title: data["title"] = title
            if course_name: data["course_name"] = course_name
            
            # Check if exists in Supabase
            res = supabase.table('requested_batch').select('*').eq('batch_id', bid_str).execute()
            if hasattr(res, 'data') and res.data:
                supabase.table('requested_batch').update(data).eq('batch_id', bid_str).execute()
            else:
                supabase.table('requested_batch').insert(data).execute()
        except Exception as e:
            print(f"Supabase save error: {e}")

def decrypt_stream(enc):
    try:
        if not enc: return None
        enc_bytes = b64decode(enc)
        k = '%!$!%_$&!%F)&^!^'.encode('utf-8')
        i = '#*y*#2yJ*#$wJv*v'.encode('utf-8')
        cipher = AES.new(k, AES.MODE_CBC, i)
        decrypted_bytes = cipher.decrypt(enc_bytes)
        try:
            plaintext = unpad(decrypted_bytes, AES.block_size).decode('utf-8')
        except:
            plaintext = decrypted_bytes.decode('utf-8', errors='ignore')
        
        cleaned_json = ''
        for idx in range(len(plaintext)):
            try:
                json.loads(plaintext[:idx+1])
                cleaned_json = plaintext[:idx+1]  
            except json.JSONDecodeError:
                continue
        final_brace_index = cleaned_json.rfind('}')
        if final_brace_index != -1:
            cleaned_json = cleaned_json[:final_brace_index + 1]
        return cleaned_json
    except Exception as e:
        print(f"Decryption error: {e}")
        return None

def encrypt_stream(plain_text):
    try:
        k = '%!$!%_$&!%F)&^!^'.encode('utf-8')
        i = '#*y*#2yJ*#$wJv*v'.encode('utf-8')
        cipher = AES.new(k, AES.MODE_CBC, i)
        padded_text = pad(plain_text.encode('utf-8'), AES.block_size)
        encrypted = cipher.encrypt(padded_text)
        return b64encode(encrypted).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return None

def encrypt(data, use_common_key, key, iv):
    cipher_key, cipher_iv = (COMMON_KEY, COMMON_IV) if use_common_key else (key, iv)
    cipher = AES.new(cipher_key, AES.MODE_CBC, cipher_iv)
    padded_data = pad(json.dumps(data, separators=(",", ":")).encode(), AES.block_size)
    encrypted = cipher.encrypt(padded_data)
    return b64encode(encrypted).decode() + ":"

def decrypt(data, use_common_key, key, iv):
    cipher_key, cipher_iv = (COMMON_KEY, COMMON_IV) if use_common_key else (key, iv)
    try:
        if not data: return None
        # Clean up data - remove any extra colons or whitespace
        data_clean = data.strip().split(":")[0]
        encrypted_data = b64decode(data_clean)
        cipher = AES.new(cipher_key, AES.MODE_CBC, cipher_iv)
        decrypted_bytes = cipher.decrypt(encrypted_data)
        
        # UTKARSH DECRYPTION TRICK:
        # Sometimes the server returns raw bytes without standard PKCS7 padding.
        # We manually check the last byte or try to decode and strip non-JSON chars.
        
        # Try standard unpadding first
        try:
            return unpad(decrypted_bytes, AES.block_size).decode('utf-8')
        except:
            # Fallback: Manual unpad and clean
            text = decrypted_bytes.decode('utf-8', errors='ignore')
            # Look for JSON structure
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                return text[start:end+1]
            return text.strip()
    except Exception as e:
        print(f"Decryption error: {e}")
        return None

def post_request_api(path, data=None, use_common_key=False, key=None, iv=None):
    try:
        current_headers = HEADERS.copy()
        if user_auth.get("jwt"): current_headers["jwt"] = user_auth["jwt"]
        if user_auth.get("userid"): current_headers["userid"] = user_auth["userid"]
        
        target_key = key if key else user_auth.get("key")
        target_iv = iv if iv else user_auth.get("iv")
        
        if not target_key or not target_iv:
            target_key, target_iv = COMMON_KEY, COMMON_IV

        encrypted_data = encrypt(data, use_common_key, target_key, target_iv) if data else data
        response = session.post(f"{API_URL}{path}", headers=current_headers, data=encrypted_data, timeout=30)
        
        # LOG RAW RESPONSE FOR DEBUGGING
        print(f"DEBUG: API Request to {path} returned status {response.status_code}")
        
        decrypted_data = decrypt(response.text, use_common_key, target_key, target_iv)
        if decrypted_data:
            # CLEAN JSON STRONGLY
            try:
                # Find first { and last }
                s = decrypted_data.find('{')
                e = decrypted_data.rfind('}')
                if s != -1 and e != -1:
                    decrypted_data = decrypted_data[s:e+1]
                return json.loads(decrypted_data)
            except Exception as json_err:
                print(f"JSON Parse Error for {path}: {json_err}")
                print(f"Raw decrypted: {decrypted_data[:100]}...")
        else:
            print(f"DEBUG: Decryption failed for {path}")
    except Exception as e:
        print(f"API Error at {path}: {e}")
    return {"status": False, "error": "Request failed"}

@app.route('/login', methods=['POST'])
def login():
    global user_auth
    mobile = os.environ.get("UTKARSH_EMAIL")
    password = os.environ.get("UTKARSH_PASSWORD")
    
    if not mobile or not password:
        return jsonify({"status": False, "error": "Missing credentials in environment"})

    try:
        r1 = session.get(base_url)
        csrf_token = r1.cookies.get('csrf_name')
        user_auth["csrf"] = csrf_token
        
        d1 = {'csrf_name': csrf_token, 'mobile': mobile, 'url': '0', 'password': password, 'submit': 'LogIn', 'device_token': 'null'}
        h = {'Host': 'online.utkarsh.com', 'Sec-Ch-Ua': '"Chromium";v="119", "Not?A_Brand";v="24"', 'Accept': 'application/json, text/javascript, */*; q=0.01', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', 'Sec-Ch-Ua-Mobile': '?0', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.199 Safari/537.36'}
        
        resp = session.post(login_url, data=d1, headers=h)
        data = resp.json() if resp and resp.status_code == 200 else {}
        dec_resp = decrypt_stream(data.get("response"))
        if not dec_resp:
            return jsonify({"status": False, "error": "Login decryption failed"})
            
        dr1 = json.loads(dec_resp)
        if dr1.get("status"):
            t = dr1.get("token")
            jwt = dr1.get("data", {}).get("jwt")
            user_auth.update({"jwt": jwt, "token": t, "login_time": time.time()})
            HEADERS["jwt"] = jwt
            
            user_auth["key"] = "".join(key_chars[int(i)] for i in ("0" + "1524567456436545")[:16]).encode()
            user_auth["iv"] = "".join(iv_chars[int(i)] for i in ("0" + "1524567456436545")[:16]).encode()
            
            profile = post_request_api("/users/get_my_profile", use_common_key=True)
            if profile and profile.get("status"):
                uid = str(profile["data"]["id"])
                user_auth.update({
                    "userid": uid,
                    "key": "".join(key_chars[int(i)] for i in (uid + "1524567456436545")[:16]).encode(),
                    "iv": "".join(iv_chars[int(i)] for i in (uid + "1524567456436545")[:16]).encode(),
                    "logged_in": True
                })
                HEADERS["userid"] = uid
                return jsonify({"status": True})
            return jsonify({"status": False, "error": "Profile failed"})
        return jsonify({"status": False, "error": dr1.get("message", "Login failed")})
    except Exception as e:
        return jsonify({"status": False, "error": str(e)})

@app.route('/batches')
def get_batches():
    if not user_auth["logged_in"]: return jsonify({"status": False, "error": "Not logged in"})
    data = post_request_api("/course/get_my_courses", data={"type": "1"})
    batches = []
    
    # Track existing batch names for requested batches
    named_batches = {}
    
    if data and data.get("status"):
        for item in data.get("data", []):
            bid = str(item.get("id"))
            btitle = item.get("title") or item.get("course_name")
            batches.append({
                "id": bid,
                "title": btitle,
                "image": "/static/images/thumbnail.png",
                "course_name": item.get("course_name")
            })
            named_batches[bid] = btitle

    requested = load_requested_batches()
    updated_requested = []
    needs_save = False

    for rid in requested:
        rid_str = str(rid)
        if not any(b['id'] == rid_str for b in batches):
            # Check if we have a saved name in DB or Supabase
            saved_title = None
            saved_course = "Requested Batch"
            
            if supabase:
                try:
                    res = supabase.table('requested_batch').select('*').eq('batch_id', rid_str).execute()
                    if hasattr(res, 'data') and res.data:
                        saved_title = res.data[0].get('title')
                        saved_course = res.data[0].get('course_name') or "Requested Batch"
                except: pass
            
            if not saved_title:
                saved = RequestedBatch.query.filter_by(batch_id=rid_str).first()
                if saved:
                    saved_title = saved.title
                    saved_course = saved.course_name or "Requested Batch"

            if rid_str in named_batches:
                real_title = named_batches[rid_str]
                batches.append({"id": rid_str, "title": real_title, "image": "/static/images/thumbnail.png", "course_name": "Requested Batch"})
                # Important: Update the DB/Supabase with the real name found
                save_batch_to_db(rid_str, title=real_title)
            elif saved_title:
                batches.append({"id": rid_str, "title": saved_title, "image": "/static/images/thumbnail.png", "course_name": saved_course})
            else:
                batches.append({"id": rid_str, "title": f"Batch {rid_str}", "image": "/static/images/thumbnail.png", "course_name": "Requested Batch"})
        updated_requested.append(rid_str)
    
    try:
        batches.sort(key=lambda x: int(x['id']), reverse=True)
    except:
        batches.sort(key=lambda x: str(x['id']), reverse=True)
    return jsonify({"status": True, "data": batches})

@app.route('/request_batch', methods=['POST'])
def request_batch():
    bid = request.json.get('batch_id')
    if not bid: return jsonify({"status": False, "error": "Batch ID required"})
    bid = str(bid).strip()
    save_batch_to_db(bid)
    return jsonify({"status": True})

@app.route('/batch/<batch_id>/content')
def get_batch_content(batch_id):
    if not user_auth["logged_in"] or (time.time() - user_auth.get("login_time", 0) > 1200):
        try: login()
        except: pass
    if not user_auth["logged_in"]: return jsonify({"status": False, "error": "Login required"})
    
    videos, pdfs, dpps = [], [], []
    h = {'Host': 'online.utkarsh.com', 'Sec-Ch-Ua': '"Chromium";v="119", "Not?A_Brand";v="24"', 'Accept': 'application/json, text/javascript, */*; q=0.01', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', 'Sec-Ch-Ua-Mobile': '?0', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.199 Safari/537.36', 'token': user_auth['token'], 'jwt': user_auth['jwt']}

    def process_layer_three(subject_id, topic_id):
        d9 = {"course_id": batch_id, "parent_id": batch_id, "layer": 3, "page": 1, "revert_api": "1#0#0#1", "subject_id": subject_id, "tile_id": 0, "topic_id": topic_id, "type": "content"}
        de4 = base64.b64encode(json.dumps(d9).encode()).decode()
        resp = session.post(layer_two_data_url, headers=h, data={'layer_two_input_data': de4, 'csrf_name': user_auth['csrf']})
        if resp.status_code != 200: return
        dec_u7 = decrypt_stream(resp.json().get("response"))
        if not dec_u7: return
        dr6 = json.loads(dec_u7)
        if dr6.get("status") and "data" in dr6 and "list" in dr6["data"]:
            for item in dr6["data"]["list"]:
                ji, jt = item.get("id"), item.get("title")
                payload = item.get("payload")
                if not payload: continue
                j4 = {"course_id": batch_id, "device_id": "server", "device_name": "server", "download_click": "0", "name": f"{ji}_0_0", "tile_id": payload.get("tile_id"), "type": "video"}
                j5 = post_request_api(meta_source_url, j4, key=user_auth['key'], iv=user_auth['iv'])
                if j5 and j5.get("data"):
                    cj = j5.get("data", {})
                    url = next((b.get("url") for b in reversed(cj.get("bitrate_urls", [])) if b.get("url")), cj.get("link", ""))
                    if url:
                        final_url = url.split("?Expires=")[0]
                        content_obj = {"id": ji, "title": jt, "url": final_url}
                        if ".pdf" in final_url.lower():
                            if "DPP" in jt.upper(): dpps.append(content_obj)
                            else: pdfs.append(content_obj)
                        else: videos.append(content_obj)

    d3 = {"course_id": batch_id, "revert_api": "1#0#0#1", "parent_id": 0, "tile_id": "15330", "layer": 1, "type": "course_combo"}
    de1 = encrypt_stream(json.dumps(d3))
    resp4 = session.post(tiles_data_url, headers=h, data={'tile_input': de1, 'csrf_name': user_auth['csrf']})
    if resp4.status_code == 200:
        dec_u4 = decrypt_stream(resp4.json().get("response"))
        if dec_u4:
            dr3 = json.loads(dec_u4)
            for layer1_item in dr3.get("data", []):
                fi = layer1_item.get("id")
                d5 = {"course_id": fi, "layer": 1, "page": 1, "parent_id": fi, "revert_api": "1#1#0#1", "tile_id": "0", "type": "content"}
                de2 = encrypt_stream(json.dumps(d5))
                resp5 = session.post(tiles_data_url, headers=h, data={'tile_input': de2, 'csrf_name': user_auth['csrf']})
                if resp5.status_code != 200: continue
                dec_u5 = decrypt_stream(resp5.json().get("response"))
                if not dec_u5: continue
                dr4 = json.loads(dec_u5)
                for subject in dr4.get("data", {}).get("list", []):
                    sfi = subject.get("id")
                    d7 = {"course_id": fi, "parent_id": fi, "layer": 2, "page": 1, "revert_api": "1#0#0#1", "subject_id": sfi, "tile_id": 0, "topic_id": sfi, "type": "content"}
                    de3 = base64.b64encode(json.dumps(d7).encode()).decode()
                    resp6 = session.post(layer_two_data_url, headers=h, data={'layer_two_input_data': de3, 'csrf_name': user_auth['csrf']})
                    if resp6.status_code != 200: continue
                    dec_u6 = decrypt_stream(resp6.json().get("response"))
                    if not dec_u6: continue
                    for topic in json.loads(dec_u6).get("data", {}).get("list", []):
                        process_layer_three(sfi, topic.get("id"))

    videos.sort(key=lambda x: str(x.get("id", "")), reverse=True)
    return jsonify({"status": True, "data": {"videos": videos, "pdfs": pdfs, "dpps": dpps}})

@app.route('/')
def index(): return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path): return send_from_directory('static', path)

if __name__ == '__main__':
    if not os.path.exists('static'): os.makedirs('static')
    app.run(host='0.0.0.0', port=5000)
