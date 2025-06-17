from flask import Flask, request, jsonify
import subprocess
import json

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ YouTube Downloader API is running."

@app.route('/info')
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400

    try:
        result = subprocess.run(
            ["yt-dlp", "-j", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            return jsonify({"error": "yt-dlp failed", "stderr": result.stderr}), 500

        video_info = json.loads(result.stdout)
        return jsonify({
            "title": video_info.get("title"),
            "duration": video_info.get("duration"),
            "uploader": video_info.get("uploader"),
            "thumbnail": video_info.get("thumbnail"),
            "formats": [
                {
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("format_note") or f.get("height"),
                    "filesize": f.get("filesize"),
                    "url": f.get("url")
                } for f in video_info.get("formats", []) if f.get("url")
            ]
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "yt-dlp timed out"}), 504
    except Exception as e:
        return jsonify({"error": "Internal error", "message": str(e)}), 500
